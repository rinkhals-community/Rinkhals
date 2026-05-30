// =============================================================================
// K3SysUi Z-offset button shim
//
// LD_PRELOAD library that restores the live Z-offset adjust button on the
// K3SysUi print page without modifying the K3SysUi binary. The popup widget,
// the dispatcher case-10 handler, and the embedded SVG icon are all still
// present in the binary; only the QPushButton on the print page that emits
// clicked() with id=10 was removed. We inject a replacement.
//
// Opt-in env vars (set by Rinkhals start.sh):
//   RINKHALS_ZOFFSET_LOG=1     log diagnostics to stderr
//   RINKHALS_ZOFFSET_INJECT=1  inject the new button (the feature itself)
//   RINKHALS_ZOFFSET_UNHIDE=1  legacy diagnostic: try to un-hide K3SysUi's
//                              own id=10 button (does not work in isolation;
//                              kept for debugging)
//
// Architecture overview:
//   - Interpose QButtonGroup::addButton via LD_PRELOAD symbol shadowing.
//   - Watch each group's id sequence; a group registering ids 0..9 in order is
//     a print-page button group. K3SysUi then adds its hidden id=10 button;
//     that callsite is our trigger to construct and add our visible button.
//   - The new QPushButton is parented to the top-level main window so its
//     coordinate space is always visible. Its clicked(bool) signal is
//     connected directly to popup->show() via Qt's string-based connect,
//     bypassing QButtonGroup routing entirely.
//   - Visibility mirrors the print page via a global event filter on qApp,
//     matching Show/Hide against an ancestor chain registered for each
//     captured template button. The filter object is a bare QObject with its
//     per-instance vtable patched at the eventFilter slot, avoiding moc.
//
// Verified targets:
//   KS1 / Anycubic firmware 2.7.2.1 / Qt 5.14.2 / ARM 32-bit hardfloat uClibc
//
// All foreign Qt construction is wrapped in a SIGSEGV/sigsetjmp trap, so any
// per-firmware structural mismatch aborts the affected step rather than
// crashing K3SysUi.
// =============================================================================

#include <dlfcn.h>
#include <signal.h>
#include <setjmp.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <stdint.h>
#include <fcntl.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <elf.h>


// =============================================================================
// Named constants (formerly magic numbers scattered through the code)
// =============================================================================

namespace constants {

// Pointer-sanity threshold. Any pointer value below this is considered invalid
// (catches null and small numeric values that aren't real addresses).
constexpr uintptr_t kMinPlausiblePointer = 0x10000;

// Anycubic-specific MainWindow member layout. The popup widget pointer lives
// at MainWindow + this offset. Verified on KS1 2.7.2.1; discover_offsets()
// finds the real value at runtime by disassembling case 10 in the dispatcher.
constexpr int kPopupOffsetFallback = 0x530;

// Capacity for runtime tracking tables.
constexpr int kMaxGroupTracks   = 32;  // tracked QButtonGroups
constexpr int kMaxAncestors     = 64;  // (ancestor, button) registrations
constexpr int kMaxAncestorHops  = 4;   // walk depth from template button
constexpr int kFindToplevelHops = 64;  // walk depth for top-level lookup

// Default button placement when the template button's geometry isn't readable.
constexpr int kDefaultBtnX = 120;
constexpr int kDefaultBtnY = 120;
constexpr int kDefaultBtnW = 50;
constexpr int kDefaultBtnH = 50;
constexpr int kIconSize    = 40;

// QPushButton allocation size. K3SysUi itself uses 40 bytes for QtCSquareBtn
// (a QPushButton subclass), so sizeof(QPushButton) <= 40. 64 leaves headroom.
constexpr int kQPushButtonAllocBytes = 64;

// Bare QObject we construct as our event filter. sizeof(QObject) is
// vtable+d_ptr = 8 on 32-bit ARM; 32 leaves space + a stash slot at +16.
constexpr int kFilterObjAllocBytes = 32;
constexpr int kFilterObjStashOff   = 16;  // where we stash our button pointer

// QObject vtable entry count we copy. Index 6 is eventFilter (after
// metaObject, qt_metacast, qt_metacall, dtor, dtor, event); 12 entries
// covers up to timerEvent etc. and is conservative.
constexpr int kVtableCopyEntries   = 12;
constexpr int kVtableIndexEventFilter = 6;

// QEvent layout: type stored as ushort at this byte offset from the QEvent
// object's base. Stable across Qt 5 ABI.
constexpr int kQEventTypeOffset = 8;

// QObject layout: d_ptr at +4 (after vtable), and within QObjectData,
// parent is at +8 (after vtable + q_ptr). Stable across Qt 5 ABI.
constexpr int kQObjectDPtrOffset    = 4;
constexpr int kQObjectDataParentOff = 8;

// ARM bl encoding: 0xeb000000 | (signed 24-bit instruction offset).
// Target = PC + 8 + offset*4.
constexpr uint32_t kArmBlOpcodeMask    = 0xff000000;
constexpr uint32_t kArmBlOpcode        = 0xeb000000;
// ldr r3, [r3, #N]  encoding (low 12 bits are immediate N).
constexpr uint32_t kArmLdrR3R3ImmMask  = 0xfffff000;
constexpr uint32_t kArmLdrR3R3Imm      = 0xe5933000;
// mov r0, r3
constexpr uint32_t kArmMovR0R3         = 0xe1a00003;

// Discovery scan window: after a matching `bl getZoffset`, look this many
// instructions forward for the popup-load pattern.
constexpr int kDiscoveryScanWindow = 50;
// Sanity bounds for the popup offset; must be a non-trivial MainWindow member.
constexpr int kPopupOffsetMin = 0x40;
constexpr int kPopupOffsetMax = 0x10000;

// Sanity bound on the print-page id sequence we accept (we expect 0..9 plus
// the hidden 10/11; anything past 12 is out of expected range).
constexpr int kMaxExpectedGroupId = 12;

}  // namespace constants


// =============================================================================
// QEvent::Type subset (just what we care about)
// =============================================================================

namespace qevent {
enum Type : unsigned short {
    Show         = 17,
    Hide         = 18,
    ShowToParent = 26,
    HideToParent = 27,
};
}


// =============================================================================
// Vtable manipulation type aliases (replaces void***/void** in raw code)
// =============================================================================
//
// A C++ object with virtual methods has a hidden vtable pointer at offset 0.
//   object_ptr[0] == vtable (= array of function pointers)
//
// In types:
//   VtableEntry = a function pointer slot              (void*)
//   Vtable      = pointer to an array of slots         (VtableEntry*)
//   VtableSlot  = where the vtable pointer lives in    (Vtable*)
//                 the object (= the object's first
//                 4 bytes, treated as a pointer-to-Vtable)
//
// Reading the current vtable:    Vtable old_vt = *vtable_slot_of(obj);
// Overriding to a per-instance copy:  *vtable_slot_of(obj) = new_vt;
//
typedef void*        VtableEntry;
typedef VtableEntry* Vtable;
typedef Vtable*      VtableSlot;

static inline VtableSlot vtable_slot_of(void* obj) {
    return reinterpret_cast<VtableSlot>(obj);
}


// =============================================================================
// Function-pointer typedefs for the Qt symbols we dlsym
// =============================================================================

namespace qtfn {
typedef void  (*addButton_t)        (void* self, void* button, int id);
typedef void  (*setGeometryRect_t)  (void* this_widget, const int* qrect4);
typedef void  (*setVisible_t)       (void* this_widget, bool);
typedef void  (*show_t)             (void* this_widget);
typedef void  (*raise_t)            (void* this_widget);
typedef void* (*qpushButton_ctor_t) (void* this_obj, void* parent_widget);
typedef void  (*setText_t)          (void* this_button, const void* qstring_ref);
typedef void  (*setStyleSheet_t)    (void* this_widget, const void* qstring_ref);
typedef void  (*qstring_fromUtf8_t) (void* result_storage,
                                     const char* utf8, int size);
typedef void  (*qstring_dtor_t)     (void* this_qstring);
typedef void* (*qicon_ctor_str_t)   (void* this_qicon, const void* qstring_ref);
typedef void  (*qicon_dtor_t)       (void* this_qicon);
typedef bool  (*qicon_isNull_t)     (const void* this_qicon);
typedef void  (*setIcon_t)          (void* this_button, const void* qicon_ref);
typedef void  (*setIconSize_t)      (void* this_button, const int* qsize2);
typedef int   (*intGetter_t)        (const void* this_widget);
typedef void* (*qobject_ctor_t)     (void* this_obj, void* parent);
typedef void  (*installEventFilter_t)(void* this_obj, void* filter);
// QObject::connect (string-based overload, sret return on ARM EABI):
//   QMetaObject::Connection connect(const QObject*, const char* signal,
//                                   const QObject*, const char* member,
//                                   Qt::ConnectionType)
// The result is a non-trivially-destructible struct returned via sret, so the
// ABI prepends a hidden result-pointer to the actual args.
typedef void  (*connect_str_t)(void* result_storage,
                               const void* sender, const char* signal,
                               const void* receiver, const char* member,
                               int conn_type);
}


// =============================================================================
// Internal state and helpers (anonymous namespace = internal linkage)
// =============================================================================

namespace {

// --- Tracking structures ---

struct GroupTrack {
    void* group;
    int   next_id;
    int   got9;    // 1 once the strict 0..9 sequence has been observed
};

struct AncestorMapping {
    void* ancestor;
    void* button;
    unsigned char seen_hide;   // set once we observe Hide on this ancestor
};

// --- Shim state ---
//
// All state is internal-linkage and grouped here so it's easy to inventory.
// Not encapsulated in a class because the LD_PRELOAD entry point and
// __attribute__((constructor)) need free access to it; a class would just
// add boilerplate without changing visibility.

qtfn::addButton_t s_real_addButton = 0;

void* s_h_widgets   = 0;   // libQt5Widgets.so.5 handle
void* s_h_core      = 0;   // libQt5Core.so.5 handle

int   s_log         = 0;   // env-driven mode flags
int   s_unhide      = 0;
int   s_inject      = 0;

int   s_call_count  = 0;
void* s_mainwindow  = 0;   // captured from top-level walk on first inject

GroupTrack       s_tracks[constants::kMaxGroupTracks];
void*            s_id10_buttons[constants::kMaxGroupTracks];
int              s_id10_count = 0;

AncestorMapping  s_ancestors[constants::kMaxAncestors];
int              s_ancestor_count = 0;

int   s_popup_offset            = constants::kPopupOffsetFallback;
int   s_popup_offset_discovered = 0;

// --- SIGSEGV trap ---

sigjmp_buf     g_jmp;
volatile int   g_jmp_armed = 0;

void segv_handler(int /*sig*/) {
    if (g_jmp_armed) { g_jmp_armed = 0; siglongjmp(g_jmp, 1); }
    signal(SIGSEGV, SIG_DFL);
    raise(SIGSEGV);
}

// --- Helpers ---

inline bool ptr_plausible(const void* p) {
    return reinterpret_cast<uintptr_t>(p) >= constants::kMinPlausiblePointer;
}

// Read parent widget pointer from a QObject-derived widget.
// Layout: widget[0]=vtable, widget[1]=d_ptr, d_ptr[2]=parent (in QObjectData).
inline void* qwidget_parent(void* widget) {
    void** widget_words = reinterpret_cast<void**>(widget);
    void*  d_ptr        = widget_words[1];
    if (!d_ptr) return 0;
    void** d_words      = reinterpret_cast<void**>(d_ptr);
    return d_words[constants::kQObjectDataParentOff / sizeof(void*)];
}

// Look up Qt libraries once; cache handles.
void resolve_qt() {
    if (!s_h_widgets) s_h_widgets = dlopen("libQt5Widgets.so.5", RTLD_LAZY | RTLD_LOCAL);
    if (!s_h_core)    s_h_core    = dlopen("libQt5Core.so.5",    RTLD_LAZY | RTLD_LOCAL);
    // QtSvg isn't linked into K3SysUi. Loading it here registers SVG as a
    // supported image format so QIcon(":/.../foo.svg") actually renders.
    static int svg_loaded = 0;
    if (!svg_loaded) {
        void* h_svg = dlopen("libQt5Svg.so.5", RTLD_LAZY | RTLD_GLOBAL);
        if (s_log) fprintf(stderr, "[zoffset] dlopen libQt5Svg.so.5 = %p\n", h_svg);
        svg_loaded = 1;
    }
}

GroupTrack* track_find_or_new(void* group) {
    for (int i = 0; i < constants::kMaxGroupTracks; i++) {
        if (s_tracks[i].group == group) return &s_tracks[i];
    }
    for (int i = 0; i < constants::kMaxGroupTracks; i++) {
        if (s_tracks[i].group == 0) {
            s_tracks[i].group   = group;
            s_tracks[i].next_id = 0;
            s_tracks[i].got9    = 0;
            return &s_tracks[i];
        }
    }
    return 0;
}

// Walk parent chain from `start` widget upwards until parent==null.
// All reads are SIGSEGV-trapped (per-firmware layouts may differ).
void* find_toplevel_ancestor(void* start) {
    void* current = start;
    for (int hops = 0; hops < constants::kFindToplevelHops; hops++) {
        void* parent = 0;
        g_jmp_armed = 1;
        if (sigsetjmp(g_jmp, 1) == 0) {
            parent = qwidget_parent(current);
        } else {
            g_jmp_armed = 0;
            break;
        }
        g_jmp_armed = 0;
        if (!ptr_plausible(parent)) break;
        current = parent;
    }
    return current;
}

// =========================================================================
// Dynamic offset discovery
//
// Reads K3SysUi's own ELF symbol table and disassembles case 10 in
// MainWindow::AcFilePrintPageUiInit's button-clicked dispatcher to extract
// the popup widget offset from MainWindow (hardcoded as 0x530 on KS1 2.7.2.1,
// but it varies per binary).
//
// Approach (no libelf, no capstone -- just ELF struct casting and ARM opcode
// pattern matching):
//   1. mmap /proc/self/exe (the K3SysUi binary; not stripped, so .symtab is
//      present).
//   2. Find MainWindow::AcDeviceLeviqGetZoffset() by mangled name. The case 10
//      handler is the only place that calls it.
//   3. Scan all of .text for `bl <getZoffset>`.
//   4. After each matching bl, scan forward for the pattern
//      `ldr r3, [r3, #N]; mov r0, r3`. The N is the popup widget offset.
//   5. Fall back to constants::kPopupOffsetFallback if discovery fails.
// =========================================================================

int decode_bl_target(uint32_t inst, uint32_t pc, uint32_t* out_target) {
    if ((inst & constants::kArmBlOpcodeMask) != constants::kArmBlOpcode) return 0;
    // Sign-extend the lower 24 bits.
    int32_t signed_offset = static_cast<int32_t>(inst << 8) >> 8;
    *out_target = pc + 8 + static_cast<uint32_t>(signed_offset * 4);
    return 1;
}

void discover_offsets() {
    if (s_popup_offset_discovered) return;
    s_popup_offset_discovered = 1;  // attempt only once

    int fd = open("/proc/self/exe", O_RDONLY);
    if (fd < 0) {
        if (s_log) fprintf(stderr, "[zoffset-discover] open /proc/self/exe failed\n");
        return;
    }
    struct stat st;
    if (fstat(fd, &st) != 0 || st.st_size < 0x1000) { close(fd); return; }

    void* base = mmap(0, st.st_size, PROT_READ, MAP_PRIVATE, fd, 0);
    close(fd);
    if (base == MAP_FAILED) {
        if (s_log) fprintf(stderr, "[zoffset-discover] mmap failed\n");
        return;
    }

    Elf32_Ehdr* ehdr = reinterpret_cast<Elf32_Ehdr*>(base);
    if (memcmp(ehdr->e_ident, ELFMAG, SELFMAG) != 0 ||
        ehdr->e_ident[EI_CLASS] != ELFCLASS32) {
        if (s_log) fprintf(stderr, "[zoffset-discover] not a valid 32-bit ELF\n");
        munmap(base, st.st_size);
        return;
    }

    // Locate .symtab, .strtab, .text via section headers.
    Elf32_Shdr* shdrs   = reinterpret_cast<Elf32_Shdr*>(
        static_cast<char*>(base) + ehdr->e_shoff);
    const char* shstrtab = static_cast<const char*>(base)
                         + shdrs[ehdr->e_shstrndx].sh_offset;
    Elf32_Shdr *symtab_shdr = 0, *strtab_shdr = 0, *text_shdr = 0;
    for (int i = 0; i < ehdr->e_shnum; i++) {
        const char* section_name = shstrtab + shdrs[i].sh_name;
        if      (strcmp(section_name, ".symtab") == 0) symtab_shdr = &shdrs[i];
        else if (strcmp(section_name, ".strtab") == 0) strtab_shdr = &shdrs[i];
        else if (strcmp(section_name, ".text")   == 0) text_shdr   = &shdrs[i];
    }
    if (!symtab_shdr || !strtab_shdr || !text_shdr) {
        if (s_log) fprintf(stderr, "[zoffset-discover] missing .symtab/.strtab/.text\n");
        munmap(base, st.st_size);
        return;
    }

    Elf32_Sym* symtab = reinterpret_cast<Elf32_Sym*>(
        static_cast<char*>(base) + symtab_shdr->sh_offset);
    const char* strtab = static_cast<const char*>(base) + strtab_shdr->sh_offset;
    int symbol_count = symtab_shdr->sh_size / sizeof(Elf32_Sym);

    // Step 1: find MainWindow::AcDeviceLeviqGetZoffset() address.
    const char* getz_mangled = "_ZN10MainWindow23AcDeviceLeviqGetZoffsetEv";
    uint32_t getz_addr = 0;
    for (int i = 0; i < symbol_count; i++) {
        if (ELF32_ST_TYPE(symtab[i].st_info) != STT_FUNC) continue;
        const char* sym_name = strtab + symtab[i].st_name;
        if (strcmp(sym_name, getz_mangled) == 0) {
            getz_addr = symtab[i].st_value;
            break;
        }
    }
    if (!getz_addr) {
        if (s_log) fprintf(stderr, "[zoffset-discover] %s not found in symbols\n", getz_mangled);
        munmap(base, st.st_size);
        return;
    }
    if (s_log) fprintf(stderr, "[zoffset-discover] AcDeviceLeviqGetZoffset @ 0x%x\n", getz_addr);

    // Step 2: Find the dispatcher lambda in AcFilePrintPageUiInit and bound
    // the scan to inside its body. There are several callers of
    // AcDeviceLeviqGetZoffset in K3SysUi (8 on KS1 2.7.2.1); only the
    // dispatcher case 10 has the popup-load pattern we want. Scanning all of
    // .text would match the first caller, which produces a wrong offset.
    //
    // The dispatcher is a lambda taking int inside
    // MainWindow::AcFilePrintPageUiInit(). Its mangled name has the form:
    //   _ZZN10MainWindow21AcFilePrintPageUiInitEvENKUliE<N>_clEi
    // where <N> is a base-36 lambda index that may differ per build. Match the
    // prefix + suffix and check each candidate for a bl to getZoffset; only
    // case 10 calls it.
    const char* lambda_prefix = "_ZZN10MainWindow21AcFilePrintPageUiInitEvENKUli";
    const char* lambda_suffix = "_clEi";
    const size_t prefix_len = strlen(lambda_prefix);
    const size_t suffix_len = strlen(lambda_suffix);

    const uint32_t text_vma  = text_shdr->sh_addr;
    const uint32_t text_file = text_shdr->sh_offset;
    const uint32_t text_size = text_shdr->sh_size;

    for (int i = 0; i < symbol_count; i++) {
        if (ELF32_ST_TYPE(symtab[i].st_info) != STT_FUNC) continue;
        const char* sym_name = strtab + symtab[i].st_name;
        const size_t name_len = strlen(sym_name);

        if (name_len <= prefix_len + suffix_len) continue;
        if (strncmp(sym_name, lambda_prefix, prefix_len) != 0) continue;
        if (strcmp(sym_name + name_len - suffix_len, lambda_suffix) != 0) continue;

        // Candidate lambda(int) inside AcFilePrintPageUiInit. Locate its body
        // in the mapped binary.
        const uint32_t lambda_addr = symtab[i].st_value;
        const uint32_t lambda_size = symtab[i].st_size;
        if (lambda_addr < text_vma) continue;
        if (lambda_addr + lambda_size > text_vma + text_size) continue;
        const uint32_t lambda_file = text_file + (lambda_addr - text_vma);
        uint32_t* lambda_code = reinterpret_cast<uint32_t*>(
            static_cast<char*>(base) + lambda_file);
        const int lambda_words = lambda_size / 4;

        // Walk this lambda looking for `bl getZoffset`. If found, this IS the
        // dispatcher case 10.
        for (int j = 0; j + 2 < lambda_words; j++) {
            uint32_t pc = lambda_addr + j * 4;
            uint32_t bl_target = 0;
            if (!decode_bl_target(lambda_code[j], pc, &bl_target)) continue;
            if (bl_target != getz_addr) continue;

            if (s_log) fprintf(stderr,
                "[zoffset-discover] found dispatcher lambda %s @ 0x%x (bl getZoffset @ 0x%x)\n",
                sym_name, lambda_addr, pc);

            // Scan forward inside this lambda for the popup-load triple:
            //   ldr r3, [r3, #N]
            //   mov r0, r3
            //   bl  <anything> (the QWidget::show call)
            int scan_end = j + constants::kDiscoveryScanWindow;
            if (scan_end > lambda_words - 3) scan_end = lambda_words - 3;
            for (int k = j + 1; k <= scan_end; k++) {
                uint32_t ldr_inst = lambda_code[k];
                uint32_t mov_inst = lambda_code[k + 1];
                uint32_t bl_inst  = lambda_code[k + 2];
                const bool is_ldr_r3_r3_imm =
                    (ldr_inst & constants::kArmLdrR3R3ImmMask) == constants::kArmLdrR3R3Imm;
                const bool is_mov_r0_r3 = (mov_inst == constants::kArmMovR0R3);
                const bool is_bl =
                    (bl_inst & constants::kArmBlOpcodeMask) == constants::kArmBlOpcode;
                if (!is_ldr_r3_r3_imm || !is_mov_r0_r3 || !is_bl) continue;

                uint32_t imm = ldr_inst & 0xfff;
                const bool plausible_member_offset =
                    imm >= static_cast<uint32_t>(constants::kPopupOffsetMin) &&
                    imm <  static_cast<uint32_t>(constants::kPopupOffsetMax);
                if (!plausible_member_offset) continue;

                s_popup_offset = static_cast<int>(imm);
                if (s_log) fprintf(stderr,
                    "[zoffset-discover] popup offset discovered: 0x%x (at .text+0x%x)\n",
                    imm, static_cast<uint32_t>((j + (k - j)) * 4 + lambda_file));
                munmap(base, st.st_size);
                return;
            }
        }
    }

    if (s_log) fprintf(stderr,
        "[zoffset-discover] dispatcher lambda not found; using fallback popup offset 0x%x\n",
        s_popup_offset);
    munmap(base, st.st_size);
}

// =========================================================================
// Event filter -- called via the per-instance vtable patch.
//
// Layout of our filter object (allocated by inject_new_button):
//   +0:  vtable* (our patched copy)
//   +4:  d_ptr (real QObject d_ptr from QObject ctor)
//   +16: our injected button pointer (stash, so the filter can find it
//        without globals -- supports multiple injects)
//
// QEvent::type() lives at offset constants::kQEventTypeOffset (8) as ushort.
// =========================================================================

bool zoffset_eventFilter(void* this_obj, void* watched, void* event) {
    if (!event || !watched) return false;

    const unsigned short event_type =
        *reinterpret_cast<unsigned short*>(
            static_cast<char*>(event) + constants::kQEventTypeOffset);

    if (event_type != qevent::Show && event_type != qevent::Hide) return false;

    for (int i = 0; i < s_ancestor_count; i++) {
        if (s_ancestors[i].ancestor != watched) continue;

        static qtfn::setVisible_t set_visible = 0;
        if (!set_visible) {
            void* h = dlopen("libQt5Widgets.so.5", RTLD_LAZY | RTLD_LOCAL);
            if (h) {
                set_visible = reinterpret_cast<qtfn::setVisible_t>(
                    dlsym(h, "_ZN7QWidget10setVisibleEb"));
            }
        }
        if (!set_visible) return false;

        const bool become_visible = (event_type == qevent::Show);
        set_visible(s_ancestors[i].button, become_visible);
        fprintf(stderr,
                "[zoffset] ancestor %s on %p -> setVisible(%d) on btn=%p\n",
                become_visible ? "SHOW" : "HIDE",
                watched, static_cast<int>(become_visible),
                s_ancestors[i].button);
        break;
    }
    (void)this_obj;  // not used; the stash is reached via watched/ancestors
    return false;    // never consume events; pass through
}

// =========================================================================
// SIGUSR1 diagnostic: replicate dispatcher case 10's popup show.
//   popup_ptr = *(MainWindow + s_popup_offset)
//   popup_ptr->show(); popup_ptr->raise();
// Used to disentangle click-routing failures from popup-display failures.
// =========================================================================

void on_sigusr1(int /*signum*/) {
    if (!s_mainwindow) {
        fprintf(stderr, "[zoffset] SIGUSR1: no MainWindow saved\n");
        return;
    }
    fprintf(stderr, "[zoffset] SIGUSR1: attempting popup->show() via MainWindow+0x%x\n",
            s_popup_offset);
    void* popup = 0;
    g_jmp_armed = 1;
    if (sigsetjmp(g_jmp, 1) != 0) {
        fprintf(stderr, "[zoffset] SIGUSR1: SEGV reading popup ptr\n");
        g_jmp_armed = 0;
        return;
    }
    popup = *reinterpret_cast<void**>(
        static_cast<char*>(s_mainwindow) + s_popup_offset);
    g_jmp_armed = 0;
    fprintf(stderr, "[zoffset] SIGUSR1: popup_ptr at MainWindow+0x%x = %p\n",
            s_popup_offset, popup);
    if (!ptr_plausible(popup)) {
        fprintf(stderr, "[zoffset] SIGUSR1: implausible popup ptr\n");
        return;
    }

    resolve_qt();
    if (!s_h_widgets) { fprintf(stderr, "[zoffset] SIGUSR1: no Qt handle\n"); return; }
    qtfn::show_t  qwidget_show  = reinterpret_cast<qtfn::show_t>(
        dlsym(s_h_widgets, "_ZN7QWidget4showEv"));
    qtfn::raise_t qwidget_raise = reinterpret_cast<qtfn::raise_t>(
        dlsym(s_h_widgets, "_ZN7QWidget5raiseEv"));

    g_jmp_armed = 1;
    if (sigsetjmp(g_jmp, 1) == 0) {
        if (qwidget_show)  qwidget_show(popup);
        if (qwidget_raise) qwidget_raise(popup);
        fprintf(stderr, "[zoffset] SIGUSR1: show()+raise() invoked on popup=%p\n", popup);
    } else {
        fprintf(stderr, "[zoffset] SIGUSR1: SEGV during show()\n");
    }
    g_jmp_armed = 0;
}

// =========================================================================
// Diagnostic un-hide: try to make K3SysUi's existing id=10 button visible.
// Does not work in isolation (the button's parent layout zero-sizes it), but
// kept as a debugging tool. Off unless RINKHALS_ZOFFSET_UNHIDE=1.
// =========================================================================

void unhide_button(void* btn) {
    resolve_qt();
    if (!s_h_widgets) {
        if (s_log) fprintf(stderr, "[zoffset] no Qt handle; cannot unhide\n");
        return;
    }

    qtfn::setVisible_t      set_visible   = reinterpret_cast<qtfn::setVisible_t>(
        dlsym(s_h_widgets, "_ZN7QWidget10setVisibleEb"));
    qtfn::show_t            qwidget_show  = reinterpret_cast<qtfn::show_t>(
        dlsym(s_h_widgets, "_ZN7QWidget4showEv"));
    qtfn::raise_t           qwidget_raise = reinterpret_cast<qtfn::raise_t>(
        dlsym(s_h_widgets, "_ZN7QWidget5raiseEv"));
    qtfn::setGeometryRect_t set_geometry  = reinterpret_cast<qtfn::setGeometryRect_t>(
        dlsym(s_h_widgets, "_ZN7QWidget11setGeometryERK5QRect"));

    if (s_log) fprintf(stderr,
        "[zoffset] unhide btn=%p: setVisible=%p show=%p raise=%p setGeometry=%p\n",
        btn, set_visible, qwidget_show, qwidget_raise, set_geometry);

    // QRect in Qt 5 is { int x1, y1, x2, y2 } where x2 = x+w-1.
    const int rect[4] = {
        constants::kDefaultBtnX,
        constants::kDefaultBtnY,
        constants::kDefaultBtnX + constants::kDefaultBtnW - 1,
        constants::kDefaultBtnY + constants::kDefaultBtnH - 1
    };

    g_jmp_armed = 1;
    if (sigsetjmp(g_jmp, 1) == 0) {
        if (set_geometry)  set_geometry(btn, rect);
        if (set_visible)   set_visible(btn, true);
        if (qwidget_show)  qwidget_show(btn);
        if (qwidget_raise) qwidget_raise(btn);
        if (s_log) fprintf(stderr, "[zoffset] btn=%p un-hidden\n", btn);
    } else {
        if (s_log) fprintf(stderr, "[zoffset] SEGV un-hiding btn=%p; skipping\n", btn);
    }
    g_jmp_armed = 0;
}

// =========================================================================
// inject_new_button: the feature itself.
//
// Constructs a fresh QPushButton parented to the top-level main window,
// gives it geometry and the embedded Z-offset SVG icon, connects its
// clicked(bool) signal directly to popup->show(), and registers ancestor
// chain entries so the global event filter mirrors visibility.
// =========================================================================

void inject_new_button(void* group, void* template_btn) {
    if (s_log) fprintf(stderr,
        "[zoffset] inject begin: group=%p template=%p\n", group, template_btn);

    void* topwidget = find_toplevel_ancestor(template_btn);
    if (s_log) fprintf(stderr, "[zoffset] top-level ancestor = %p\n", topwidget);
    if (!ptr_plausible(topwidget)) {
        if (s_log) fprintf(stderr, "[zoffset] no valid top-level; abort inject\n");
        return;
    }
    if (!s_mainwindow) {
        s_mainwindow = topwidget;
        if (s_log) fprintf(stderr,
            "[zoffset] saved MainWindow=%p for SIGUSR1 diagnostic\n", topwidget);
    }

    resolve_qt();
    if (!s_h_widgets || !s_h_core) {
        if (s_log) fprintf(stderr, "[zoffset] no Qt libs; abort inject\n");
        return;
    }

    // Resolve Qt entry points. C1 is the complete-object ctor; if missing,
    // C2 (base-object ctor) is functionally equivalent for a standalone obj.
    qtfn::qpushButton_ctor_t qpush_ctor = reinterpret_cast<qtfn::qpushButton_ctor_t>(
        dlsym(s_h_widgets, "_ZN11QPushButtonC1EP7QWidget"));
    if (!qpush_ctor) qpush_ctor = reinterpret_cast<qtfn::qpushButton_ctor_t>(
        dlsym(s_h_widgets, "_ZN11QPushButtonC2EP7QWidget"));

    qtfn::setGeometryRect_t set_geometry = reinterpret_cast<qtfn::setGeometryRect_t>(
        dlsym(s_h_widgets, "_ZN7QWidget11setGeometryERK5QRect"));
    qtfn::show_t            qwidget_show = reinterpret_cast<qtfn::show_t>(
        dlsym(s_h_widgets, "_ZN7QWidget4showEv"));
    qtfn::raise_t           qwidget_raise = reinterpret_cast<qtfn::raise_t>(
        dlsym(s_h_widgets, "_ZN7QWidget5raiseEv"));

    qtfn::qstring_fromUtf8_t qstr_fromUtf8 = reinterpret_cast<qtfn::qstring_fromUtf8_t>(
        dlsym(s_h_core, "_ZN7QString15fromUtf8_helperEPKci"));
    qtfn::qstring_dtor_t     qstr_dtor     = reinterpret_cast<qtfn::qstring_dtor_t>(
        dlsym(s_h_core, "_ZN7QStringD1Ev"));
    if (!qstr_dtor) qstr_dtor = reinterpret_cast<qtfn::qstring_dtor_t>(
        dlsym(s_h_core, "_ZN7QStringD2Ev"));

    if (s_log) fprintf(stderr,
        "[zoffset] syms: qpush_ctor=%p set_geometry=%p show=%p qstr_fromUtf8=%p\n",
        qpush_ctor, set_geometry, qwidget_show, qstr_fromUtf8);
    if (!qpush_ctor || !qwidget_show) {
        if (s_log) fprintf(stderr, "[zoffset] essential symbol missing; abort\n");
        return;
    }

    // Allocate and construct the new button.
    void* btn = calloc(1, constants::kQPushButtonAllocBytes);
    if (!btn) return;

    g_jmp_armed = 1;
    if (sigsetjmp(g_jmp, 1) != 0) {
        if (s_log) fprintf(stderr, "[zoffset] SEGV constructing QPushButton; abort\n");
        g_jmp_armed = 0;
        free(btn);
        return;
    }
    qpush_ctor(btn, topwidget);
    g_jmp_armed = 0;
    if (s_log) fprintf(stderr,
        "[zoffset] constructed new QPushButton at %p (parent=%p)\n",
        btn, topwidget);

    // ---- Geometry: copy K3SysUi's intended placement if readable ----

    qtfn::intGetter_t qw_x      = reinterpret_cast<qtfn::intGetter_t>(
        dlsym(s_h_widgets, "_ZNK7QWidget1xEv"));
    qtfn::intGetter_t qw_y      = reinterpret_cast<qtfn::intGetter_t>(
        dlsym(s_h_widgets, "_ZNK7QWidget1yEv"));
    qtfn::intGetter_t qw_width  = reinterpret_cast<qtfn::intGetter_t>(
        dlsym(s_h_widgets, "_ZNK7QWidget5widthEv"));
    qtfn::intGetter_t qw_height = reinterpret_cast<qtfn::intGetter_t>(
        dlsym(s_h_widgets, "_ZNK7QWidget6heightEv"));

    int btn_x = constants::kDefaultBtnX;
    int btn_y = constants::kDefaultBtnY;
    int btn_w = constants::kDefaultBtnW;
    int btn_h = constants::kDefaultBtnH;
    if (qw_x && qw_y && qw_width && qw_height) {
        g_jmp_armed = 1;
        if (sigsetjmp(g_jmp, 1) == 0) {
            const int tx = qw_x(template_btn);
            const int ty = qw_y(template_btn);
            const int tw = qw_width(template_btn);
            const int th = qw_height(template_btn);
            if (s_log) fprintf(stderr,
                "[zoffset] template geometry: x=%d y=%d w=%d h=%d\n", tx, ty, tw, th);
            const bool template_has_real_geom =
                tw > 0 && th > 0 && tx >= 0 && ty >= 0;
            if (template_has_real_geom) {
                btn_x = tx; btn_y = ty; btn_w = tw; btn_h = th;
            }
        }
        g_jmp_armed = 0;
    }

    const int rect[4] = { btn_x, btn_y, btn_x + btn_w - 1, btn_y + btn_h - 1 };
    g_jmp_armed = 1;
    if (sigsetjmp(g_jmp, 1) == 0 && set_geometry) set_geometry(btn, rect);
    g_jmp_armed = 0;
    if (s_log) fprintf(stderr,
        "[zoffset] new button placed at (%d,%d) %dx%d\n",
        btn_x, btn_y, btn_w, btn_h);

    // ---- Icon: load the embedded SVG Anycubic already ships ----

    qtfn::qicon_ctor_str_t qicon_ctor = reinterpret_cast<qtfn::qicon_ctor_str_t>(
        dlsym(s_h_widgets, "_ZN5QIconC1ERK7QString"));
    if (!qicon_ctor) qicon_ctor = reinterpret_cast<qtfn::qicon_ctor_str_t>(
        dlsym(s_h_widgets, "_ZN5QIconC2ERK7QString"));
    qtfn::qicon_dtor_t     qicon_dtor   = reinterpret_cast<qtfn::qicon_dtor_t>(
        dlsym(s_h_widgets, "_ZN5QIconD1Ev"));
    if (!qicon_dtor) qicon_dtor = reinterpret_cast<qtfn::qicon_dtor_t>(
        dlsym(s_h_widgets, "_ZN5QIconD2Ev"));
    qtfn::setIcon_t        set_icon     = reinterpret_cast<qtfn::setIcon_t>(
        dlsym(s_h_widgets, "_ZN15QAbstractButton7setIconERK5QIcon"));
    qtfn::qicon_isNull_t   qicon_isNull = reinterpret_cast<qtfn::qicon_isNull_t>(
        dlsym(s_h_widgets, "_ZNK5QIcon6isNullEv"));
    qtfn::setIconSize_t    set_icon_size = reinterpret_cast<qtfn::setIconSize_t>(
        dlsym(s_h_widgets, "_ZN15QAbstractButton11setIconSizeERK5QSize"));

    if (s_log) fprintf(stderr,
        "[zoffset] icon syms: qicon_ctor=%p qicon_dtor=%p set_icon=%p\n",
        qicon_ctor, qicon_dtor, set_icon);

    if (qstr_fromUtf8 && qicon_ctor && set_icon) {
        // Try the real Z-offset SVG first; fall back to a known-loadable PNG
        // for diagnostics (so we know whether the resource bundle is reachable
        // at all when SVG fails).
        const char* icon_paths[] = {
            ":/FilePrintPage/Zoffset_Item.svg",
            ":/FilePrintPage/Pause-nor.png",
            0
        };
        for (int i = 0; icon_paths[i]; i++) {
            char qstr_storage[8] = {0};
            char qicon_storage[8] = {0};
            bool icon_is_null = true;

            g_jmp_armed = 1;
            if (sigsetjmp(g_jmp, 1) == 0) {
                // fromUtf8_helper requires an explicit length (no -1 sentinel).
                const int path_len = static_cast<int>(strlen(icon_paths[i]));
                qstr_fromUtf8(qstr_storage, icon_paths[i], path_len);
                qicon_ctor(qicon_storage, qstr_storage);
                if (qicon_isNull) icon_is_null = qicon_isNull(qicon_storage);

                if (s_log) fprintf(stderr,
                    "[zoffset] icon[%s] isNull=%d\n", icon_paths[i], (int)icon_is_null);

                if (!icon_is_null) {
                    set_icon(btn, qicon_storage);
                    const int qsize[2] = { constants::kIconSize, constants::kIconSize };
                    if (set_icon_size) set_icon_size(btn, qsize);
                    if (s_log) fprintf(stderr,
                        "[zoffset] applied icon %s + iconSize(%d,%d)\n",
                        icon_paths[i], constants::kIconSize, constants::kIconSize);
                }

                if (qicon_dtor) qicon_dtor(qicon_storage);
                if (qstr_dtor)  qstr_dtor(qstr_storage);
            }
            g_jmp_armed = 0;
            if (!icon_is_null) break;
        }
    }

    // ---- Show and register with the group (group routing is a backup) ----

    g_jmp_armed = 1;
    if (sigsetjmp(g_jmp, 1) == 0) {
        qwidget_show(btn);
        if (qwidget_raise) qwidget_raise(btn);
        if (s_real_addButton) s_real_addButton(group, btn, 10);
        if (s_log) fprintf(stderr,
            "[zoffset] new button %p shown + addButton(group=%p,id=10) done\n",
            btn, group);
    } else {
        if (s_log) fprintf(stderr,
            "[zoffset] SEGV during show/addButton; partial inject\n");
    }
    g_jmp_armed = 0;

    // ---- Visibility mirror: per-instance vtable patch + global filter ----

    qtfn::qobject_ctor_t qobject_ctor = reinterpret_cast<qtfn::qobject_ctor_t>(
        dlsym(s_h_core, "_ZN7QObjectC1EPS_"));
    if (!qobject_ctor) qobject_ctor = reinterpret_cast<qtfn::qobject_ctor_t>(
        dlsym(s_h_core, "_ZN7QObjectC2EPS_"));
    qtfn::installEventFilter_t install_filter =
        reinterpret_cast<qtfn::installEventFilter_t>(
            dlsym(s_h_core, "_ZN7QObject18installEventFilterEPS_"));
    static qtfn::setVisible_t set_visible_for_init = 0;
    if (!set_visible_for_init) {
        set_visible_for_init = reinterpret_cast<qtfn::setVisible_t>(
            dlsym(s_h_widgets, "_ZN7QWidget10setVisibleEb"));
    }
    if (s_log) fprintf(stderr,
        "[zoffset] mirror syms: qobject_ctor=%p install_filter=%p set_visible=%p\n",
        qobject_ctor, install_filter, set_visible_for_init);

    if (qobject_ctor && install_filter && set_visible_for_init) {
        void* filter_obj = calloc(1, constants::kFilterObjAllocBytes);
        if (!filter_obj) return;

        g_jmp_armed = 1;
        if (sigsetjmp(g_jmp, 1) != 0) {
            if (s_log) fprintf(stderr, "[zoffset] SEGV during event filter install\n");
            g_jmp_armed = 0;
            free(filter_obj);
            return;
        }

        qobject_ctor(filter_obj, /*parent*/0);
        if (s_log) fprintf(stderr,
            "[zoffset] constructed event-filter QObject at %p\n", filter_obj);

        // -- Per-instance vtable patch --
        //
        // Allocate a Vtable copy with kVtableCopyEntries slots, copy the
        // QObject vtable's leading entries, override slot kVtableIndexEventFilter
        // (= eventFilter) to point at our function, then redirect the object's
        // vtable slot to the copy. Only this single instance sees our patched
        // vtable; all other QObjects in the process keep the shared one.
        Vtable old_vt = *vtable_slot_of(filter_obj);
        Vtable new_vt = static_cast<Vtable>(
            malloc(sizeof(VtableEntry) * constants::kVtableCopyEntries));
        for (int i = 0; i < constants::kVtableCopyEntries; i++) {
            new_vt[i] = old_vt[i];
        }
        new_vt[constants::kVtableIndexEventFilter] =
            reinterpret_cast<VtableEntry>(&zoffset_eventFilter);

        // Stash our button pointer at +kFilterObjStashOff (past d_ptr) so the
        // filter can find it without going through globals, supporting more
        // than one inject in the same process.
        *reinterpret_cast<void**>(
            static_cast<char*>(filter_obj) + constants::kFilterObjStashOff) = btn;

        *vtable_slot_of(filter_obj) = new_vt;

        // Register the first kMaxAncestorHops ancestors of template_btn.
        // The page widget is always close to its children; higher ancestors
        // (MainWindow, QStackedWidget root) fire Show only once at boot and
        // would be false positives.
        void* ancestor = template_btn;
        for (int hops = 0; hops < constants::kMaxAncestorHops; hops++) {
            if (s_ancestor_count < constants::kMaxAncestors) {
                s_ancestors[s_ancestor_count].ancestor  = ancestor;
                s_ancestors[s_ancestor_count].button    = btn;
                s_ancestors[s_ancestor_count].seen_hide = 0;
                s_ancestor_count++;
                if (s_log) fprintf(stderr,
                    "[zoffset] registered ancestor[%d]=%p -> btn=%p\n",
                    s_ancestor_count - 1, ancestor, btn);
            }
            void* parent = qwidget_parent(ancestor);
            if (!ptr_plausible(parent)) break;
            ancestor = parent;
        }

        // Install the global filter on qApp exactly once.
        static int global_filter_installed = 0;
        if (!global_filter_installed) {
            static void** qcore_app_self = 0;
            if (!qcore_app_self) {
                qcore_app_self = reinterpret_cast<void**>(
                    dlsym(s_h_core, "_ZN16QCoreApplication4selfE"));
            }
            void* qapp = qcore_app_self ? *qcore_app_self : 0;
            if (qapp) {
                install_filter(qapp, filter_obj);
                global_filter_installed = 1;
                if (s_log) fprintf(stderr,
                    "[zoffset] GLOBAL event filter installed on qApp=%p\n", qapp);
            }
        }

        // Start the button HIDDEN. K3SysUi boots on the home page; the filter
        // will show it when the print page becomes visible.
        set_visible_for_init(btn, false);
        if (s_log) fprintf(stderr,
            "[zoffset] initial visibility set to false (filter will show on Show)\n");

        g_jmp_armed = 0;
    }

    // ---- Primary routing: connect clicked() directly to popup->show() ----
    //
    // QObject::connect (string-based, with ConnectionType arg). The return
    // value (QMetaObject::Connection) has a non-trivial dtor, so on ARM EABI
    // it's returned via sret -- a hidden result-pointer is prepended to the
    // real args. Hence 6 args total in the actual ABI call.

    qtfn::connect_str_t connect_str = reinterpret_cast<qtfn::connect_str_t>(
        dlsym(s_h_core, "_ZN7QObject7connectEPKS_PKcS1_S3_N2Qt14ConnectionTypeE"));
    if (s_log) fprintf(stderr,
        "[zoffset] connectStr=%p, MainWindow=%p\n", connect_str, s_mainwindow);

    if (connect_str && s_mainwindow) {
        void* popup = 0;
        g_jmp_armed = 1;
        if (sigsetjmp(g_jmp, 1) == 0) {
            popup = *reinterpret_cast<void**>(
                static_cast<char*>(s_mainwindow) + s_popup_offset);
        }
        g_jmp_armed = 0;
        if (s_log) fprintf(stderr, "[zoffset] popup widget = %p\n", popup);

        if (ptr_plausible(popup)) {
            // QMetaObject::Connection is sizeof(void*) = 4. 8 leaves slack.
            char conn_storage[8] = {0};
            g_jmp_armed = 1;
            if (sigsetjmp(g_jmp, 1) == 0) {
                // QAbstractButton::clicked(bool checked = false): the bool arg
                // must appear in the signal signature (no `clicked()` overload
                // exists). The slot `show()` takes nothing; Qt allows the
                // signal-to-slot arity mismatch (extra args are discarded).
                connect_str(conn_storage,
                            btn,    "2clicked(bool)",
                            popup,  "1show()",
                            /*Qt::AutoConnection*/ 0);
                void* conn_d_ptr = *reinterpret_cast<void**>(conn_storage);
                if (s_log) fprintf(stderr,
                    "[zoffset] direct connect btn->clicked => popup->show() conn.d_ptr=%p\n",
                    conn_d_ptr);
            } else {
                if (s_log) fprintf(stderr,
                    "[zoffset] SEGV during string-based connect\n");
            }
            g_jmp_armed = 0;
        }
    }
}

}  // anonymous namespace


// =============================================================================
// LD_PRELOAD entry point: interposed QButtonGroup::addButton.
//
// The dynamic linker resolves K3SysUi's call to QButtonGroup::addButton to
// this exported symbol (LD_PRELOAD libs are searched first). We always
// forward to the real libQt5Widgets implementation via RTLD_NEXT.
// =============================================================================

extern "C" __attribute__((visibility("default")))
void _ZN12QButtonGroup9addButtonEP15QAbstractButtoni(void* self, void* button, int id) {
    if (!s_real_addButton) {
        s_real_addButton = reinterpret_cast<qtfn::addButton_t>(
            dlsym(RTLD_NEXT, "_ZN12QButtonGroup9addButtonEP15QAbstractButtoni"));
    }
    if (!s_real_addButton) return;

    s_real_addButton(self, button, id);

    // Tracking is required by both unhide and inject paths (both depend on
    // detecting the print-page group via its 0..9 id sequence). Only skip
    // entirely when no mode is active.
    if (!s_log && !s_unhide && !s_inject) return;

    s_call_count++;
    if (s_log) fprintf(stderr,
        "[zoffset] #%d addButton(group=%p, btn=%p, id=%d)\n",
        s_call_count, self, button, id);

    GroupTrack* track = track_find_or_new(self);
    if (!track) return;

    // Track strict 0..9 sequence (the print-page button-construction loop).
    // After id=9 increments next_id to 10, the next addButton(id=10) is the
    // existing K3SysUi-built button we capture and inject alongside.
    if (id == 0) {
        track->next_id = 1;
        track->got9    = 0;
        return;
    }

    if (id == track->next_id) {
        track->next_id++;

        if (id == 9) {
            track->got9 = 1;
            if (s_log) fprintf(stderr,
                "[zoffset] group=%p completed 0..9 (print-page candidate)\n", self);
            return;
        }

        const bool is_template_button =
            id == 10 && track->got9 && s_id10_count < constants::kMaxGroupTracks;
        if (is_template_button) {
            s_id10_buttons[s_id10_count++] = button;
            if (s_log) fprintf(stderr,
                "[zoffset] captured existing id=10 button on print-page group=%p btn=%p (#%d total)\n",
                self, button, s_id10_count);
            if (s_unhide) unhide_button(button);
            if (s_inject) inject_new_button(self, button);
        }
        return;
    }

    // Out-of-sequence id: reset tracking for this group so a later 0..9
    // attempt can re-trigger.
    if (id < track->next_id || id > constants::kMaxExpectedGroupId) {
        track->next_id = 0;
        track->got9    = 0;
    }
}


// =============================================================================
// Constructor: env-var setup, signal handlers, dynamic offset discovery.
// Runs at LD_PRELOAD load time, before main().
// =============================================================================

__attribute__((constructor))
static void rinkhals_zoffset_init() {
    setvbuf(stderr, 0, _IOLBF, 0);

    const char* env_log    = getenv("RINKHALS_ZOFFSET_LOG");
    const char* env_unhide = getenv("RINKHALS_ZOFFSET_UNHIDE");
    const char* env_inject = getenv("RINKHALS_ZOFFSET_INJECT");
    s_log    = env_log    && env_log[0]    == '1';
    s_unhide = env_unhide && env_unhide[0] == '1';
    s_inject = env_inject && env_inject[0] == '1';

    if (s_log || s_unhide || s_inject) {
        struct sigaction segv_act = {};
        segv_act.sa_handler = segv_handler;
        segv_act.sa_flags   = SA_NODEFER;
        sigaction(SIGSEGV, &segv_act, 0);

        struct sigaction usr1_act = {};
        usr1_act.sa_handler = on_sigusr1;
        sigaction(SIGUSR1, &usr1_act, 0);

        fprintf(stderr,
            "[zoffset] loaded pid=%d (log=%d unhide=%d inject=%d) SIGUSR1=popup-show\n",
            static_cast<int>(getpid()), s_log, s_unhide, s_inject);

        // Discover Anycubic-specific offsets from the K3SysUi binary now so
        // subsequent code paths pick up the discovered value (or fall back).
        discover_offsets();
    }

    memset(s_tracks,        0, sizeof(s_tracks));
    memset(s_id10_buttons,  0, sizeof(s_id10_buttons));
    s_id10_count = 0;
}
