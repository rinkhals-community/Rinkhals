// rinkhals-zoffset-shim.cpp - PHASE 2b
//
// Key finding from phase-2: K3SysUi *itself* registers buttons with id=10 (and
// id=11) on the print-page group(s). The button exists; it's just not visible.
// So instead of constructing a new QPushButton, we capture the pointer of the
// existing id=10 button and call setVisible(true) + setGeometry + raise() on it.
//
// Opt-in env vars:
//   RINKHALS_ZOFFSET_LOG=1     log addButton calls
//   RINKHALS_ZOFFSET_UNHIDE=1  capture and un-hide existing id=10 buttons
//
// The track table is also bumped from 4 to 32 slots since the print page is
// initialized several groups deep into K3SysUi startup.

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

extern "C" {

typedef void  (*addButton_fn)(void* self, void* button, int id);
typedef void  (*setGeomRect_fn)(void* this_, const int* qrect4_ints);  // setGeometry(QRect const&)
typedef void  (*setVisible_fn)(void* this_, bool);
typedef void  (*show_fn)     (void* this_);
typedef void  (*raise_fn)    (void* this_);
typedef void* (*qpush_ctor_fn)(void* this_, void* parent);
typedef void  (*setText_fn)  (void* this_, const void* qstring_ref);
typedef void  (*setStyle_fn) (void* this_, const void* qstring_ref);
// QString::QString(const char*) is inline in Qt 5.14 (not exported). Use
// QString::fromUtf8_helper(const char*, int) instead - exported as sret.
typedef void (*qstring_from_utf8_fn)(void* result_storage, const char* utf8, int size);
// Old typedef kept for the setText/setStyle paths (they use QString const&,
// constructed via fromUtf8 into the same stack storage).
typedef void* (*qstring_ctor_fn)(void* this_, const char* utf8);
typedef void  (*qstring_dtor_fn)(void* this_);

static addButton_fn   s_real_addButton = 0;
static void*          s_h_widgets  = 0;
static void*          s_h_core     = 0;
static int            s_log    = 0;
static int            s_unhide = 0;
static int            s_inject = 0;
static int            s_call_count = 0;
static void*          s_mainwindow = 0;

#define MAX_TRACKS 32
struct GroupTrack { void* group; int next_id; int got9; };
static GroupTrack s_tracks[MAX_TRACKS];

// Captured "id=10 button on a print-page group" pointers
static void* s_id10_buttons[MAX_TRACKS];
static int   s_id10_count = 0;

// SIGSEGV trap
static sigjmp_buf g_jmp;
static volatile int g_jmp_armed = 0;
static void segv_handler(int sig) {
    if (g_jmp_armed) { g_jmp_armed = 0; siglongjmp(g_jmp, 1); }
    signal(SIGSEGV, SIG_DFL); raise(SIGSEGV);
}

static GroupTrack* track_find_or_new(void* group) {
    for (int i = 0; i < MAX_TRACKS; i++) if (s_tracks[i].group == group) return &s_tracks[i];
    for (int i = 0; i < MAX_TRACKS; i++) if (s_tracks[i].group == 0)     {
        s_tracks[i].group = group;
        s_tracks[i].next_id = 0;
        s_tracks[i].got9 = 0;
        return &s_tracks[i];
    }
    return 0;
}

// Look up Qt libs once.
static void resolve_qt(void) {
    if (!s_h_widgets) s_h_widgets = dlopen("libQt5Widgets.so.5", RTLD_LAZY | RTLD_LOCAL);
    if (!s_h_core)    s_h_core    = dlopen("libQt5Core.so.5",    RTLD_LAZY | RTLD_LOCAL);
    // QtSvg isn't linked into K3SysUi. Loading it here registers SVG as a
    // supported image format so QIcon(":/.../foo.svg") actually renders.
    static int svg_loaded = 0;
    if (!svg_loaded) {
        void* h_svg = dlopen("libQt5Svg.so.5", RTLD_LAZY | RTLD_GLOBAL);
        if (s_log) fprintf(stderr, "[zoffset-2b] dlopen libQt5Svg.so.5 = %p\n", h_svg);
        svg_loaded = 1;
    }
}

// Forward declaration: event filter defined later, used by inject_new_button.
bool zoffset_eventFilter(void* this_obj, void* watched, void* event);

// =========================================================================
// Dynamic offset discovery
//
// Reads K3SysUi's own ELF symbol table and disassembles the relevant case 10
// handler in MainWindow::AcFilePrintPageUiInit's button-clicked dispatcher to
// extract the popup widget offset from MainWindow (hardcoded as 0x530 on KS1
// 2.7.2.1, but varies per binary).
//
// Approach (no libelf, no capstone - just ELF struct casting and ARM opcode
// pattern matching):
//   1. mmap /proc/self/exe (the K3SysUi binary; not stripped, so .symtab is
//      present).
//   2. Find MainWindow::AcDeviceLeviqGetZoffset() by mangled name. The case 10
//      handler is the only place that calls it.
//   3. Scan all of .text for `bl <getZoffset>`. ARM bl encoding:
//        0xeb000000 | (signed 24-bit instruction offset)
//        target = PC + 8 + offset*4
//   4. After each matching bl, scan forward up to ~50 instructions for the
//      pattern  `ldr r3, [r3, #N]; mov r0, r3`. The N is the popup widget
//      offset. (This pair specifically loads the popup pointer right before
//      `bl QWidget::show()@plt`.)
//   5. Fall back to the KS1 2.7.2.1 known value of 0x530 if discovery fails.
// =========================================================================

static int s_popup_offset = 0x530;       // default; replaced by discover_offsets()
static int s_popup_offset_discovered = 0;

static int decode_bl_target(uint32_t inst, uint32_t pc, uint32_t* out_target) {
    if ((inst & 0xff000000) != 0xeb000000) return 0;
    int32_t off = (int32_t)(inst << 8) >> 8; // sign-extend lower 24 bits
    *out_target = pc + 8 + (uint32_t)(off * 4);
    return 1;
}

static void discover_offsets(void) {
    if (s_popup_offset_discovered) return;
    s_popup_offset_discovered = 1; // attempt only once

    int fd = open("/proc/self/exe", O_RDONLY);
    if (fd < 0) { if (s_log) fprintf(stderr, "[zoffset-discover] open /proc/self/exe failed\n"); return; }
    struct stat st;
    if (fstat(fd, &st) != 0 || st.st_size < 0x1000) { close(fd); return; }

    void* base = mmap(0, st.st_size, PROT_READ, MAP_PRIVATE, fd, 0);
    close(fd);
    if (base == MAP_FAILED) { if (s_log) fprintf(stderr, "[zoffset-discover] mmap failed\n"); return; }

    Elf32_Ehdr* eh = (Elf32_Ehdr*)base;
    if (memcmp(eh->e_ident, ELFMAG, SELFMAG) != 0 || eh->e_ident[EI_CLASS] != ELFCLASS32) {
        if (s_log) fprintf(stderr, "[zoffset-discover] not a valid 32-bit ELF\n");
        munmap(base, st.st_size);
        return;
    }

    // Section headers
    Elf32_Shdr* sh = (Elf32_Shdr*)((char*)base + eh->e_shoff);
    const char* shstrtab = (const char*)base + sh[eh->e_shstrndx].sh_offset;
    Elf32_Shdr *symtab_sh = 0, *strtab_sh = 0, *text_sh = 0;
    for (int i = 0; i < eh->e_shnum; i++) {
        const char* name = shstrtab + sh[i].sh_name;
        if      (strcmp(name, ".symtab") == 0) symtab_sh = &sh[i];
        else if (strcmp(name, ".strtab") == 0) strtab_sh = &sh[i];
        else if (strcmp(name, ".text")   == 0) text_sh   = &sh[i];
    }
    if (!symtab_sh || !strtab_sh || !text_sh) {
        if (s_log) fprintf(stderr, "[zoffset-discover] missing .symtab/.strtab/.text\n");
        munmap(base, st.st_size);
        return;
    }

    Elf32_Sym* syms = (Elf32_Sym*)((char*)base + symtab_sh->sh_offset);
    const char* strs = (const char*)base + strtab_sh->sh_offset;
    int nsyms = symtab_sh->sh_size / sizeof(Elf32_Sym);

    // Step 1: find MainWindow::AcDeviceLeviqGetZoffset() address.
    const char* getz_name = "_ZN10MainWindow23AcDeviceLeviqGetZoffsetEv";
    uint32_t getz_addr = 0;
    for (int i = 0; i < nsyms; i++) {
        if (ELF32_ST_TYPE(syms[i].st_info) != STT_FUNC) continue;
        const char* nm = strs + syms[i].st_name;
        if (strcmp(nm, getz_name) == 0) { getz_addr = syms[i].st_value; break; }
    }
    if (!getz_addr) {
        if (s_log) fprintf(stderr, "[zoffset-discover] %s not found in symbols\n", getz_name);
        munmap(base, st.st_size);
        return;
    }
    if (s_log) fprintf(stderr, "[zoffset-discover] AcDeviceLeviqGetZoffset @ 0x%x\n", getz_addr);

    // Step 2: scan .text for bl <getz> followed by  ldr r3,[r3,#N]; mov r0,r3
    uint32_t text_vma  = text_sh->sh_addr;
    uint32_t text_file = text_sh->sh_offset;
    uint32_t text_size = text_sh->sh_size;
    uint32_t* code = (uint32_t*)((char*)base + text_file);
    int nwords = text_size / 4;

    for (int i = 0; i + 1 < nwords; i++) {
        uint32_t pc = text_vma + i * 4;
        uint32_t target = 0;
        if (!decode_bl_target(code[i], pc, &target)) continue;
        if (target != getz_addr) continue;

        // Found bl to getZoffset. Scan forward for the popup-load pattern.
        int max_j = i + 50;
        if (max_j >= nwords - 1) max_j = nwords - 2;
        for (int j = i + 1; j <= max_j; j++) {
            uint32_t ldr = code[j];
            uint32_t mov = code[j + 1];
            // ldr r3, [r3, #N]   = 0xE5933NNN
            // mov r0, r3         = 0xE1A00003
            if ((ldr & 0xfffff000) == 0xe5933000 && mov == 0xe1a00003) {
                uint32_t n = ldr & 0xfff;
                // Sanity: popup offset should be a non-trivial MainWindow member
                if (n >= 0x40 && n < 0x10000) {
                    s_popup_offset = (int)n;
                    if (s_log) fprintf(stderr,
                        "[zoffset-discover] popup offset discovered: 0x%x (at .text+0x%x)\n",
                        n, (uint32_t)(j * 4 + text_file));
                    munmap(base, st.st_size);
                    return;
                }
            }
        }
    }

    if (s_log) fprintf(stderr, "[zoffset-discover] pattern not matched; using fallback popup offset 0x%x\n", s_popup_offset);
    munmap(base, st.st_size);
}

// Registry: each entry maps an ancestor widget pointer to our injected button.
// When the global event filter sees Show/Hide on any registered ancestor, we
// toggle the corresponding button's visibility.
struct AncestorMapping {
    void* ancestor;
    void* button;
    unsigned char seen_hide;  // set once we observe a Hide on this ancestor
};
static AncestorMapping s_ancestors[64];
static int s_ancestor_count = 0;

// Walk parent chain from `start` widget upwards until parent==null (top-level).
// All reads are SIGSEGV-trapped.
static void* find_toplevel_ancestor(void* start) {
    void* cur = start;
    for (int hops = 0; hops < 64; hops++) {
        void* parent = 0;
        g_jmp_armed = 1;
        if (sigsetjmp(g_jmp, 1) == 0) {
            void** w = (void**)cur;
            void*  d = w[1];
            if (d) parent = ((void**)d)[2];
        } else { g_jmp_armed = 0; break; }
        g_jmp_armed = 0;
        if (!parent || (uintptr_t)parent < 0x10000) break;
        cur = parent;
    }
    return cur;
}

// Construct a new QPushButton parented to the top-level ancestor of `template_btn`,
// position it visibly, add it to `group` with id=10. Body fully SIGSEGV-trapped.
static void inject_new_button(void* group, void* template_btn) {
    if (s_log) fprintf(stderr, "[zoffset-2b] inject begin: group=%p template=%p\n", group, template_btn);

    void* topwidget = find_toplevel_ancestor(template_btn);
    if (s_log) fprintf(stderr, "[zoffset-2b] top-level ancestor = %p\n", topwidget);
    if ((uintptr_t)topwidget < 0x10000) {
        if (s_log) fprintf(stderr, "[zoffset-2b] no valid top-level; abort inject\n");
        return;
    }
    if (!s_mainwindow) {
        s_mainwindow = topwidget;
        if (s_log) fprintf(stderr, "[zoffset-2b] saved MainWindow=%p for SIGUSR1 diagnostic\n", topwidget);
    }

    resolve_qt();
    if (!s_h_widgets || !s_h_core) { if (s_log) fprintf(stderr, "[zoffset-2b] no Qt libs; abort inject\n"); return; }

    qpush_ctor_fn   ctor      = (qpush_ctor_fn)   dlsym(s_h_widgets, "_ZN11QPushButtonC1EP7QWidget");
    if (!ctor) ctor           = (qpush_ctor_fn)   dlsym(s_h_widgets, "_ZN11QPushButtonC2EP7QWidget");
    setGeomRect_fn  setGeomR  = (setGeomRect_fn)  dlsym(s_h_widgets, "_ZN7QWidget11setGeometryERK5QRect");
    setText_fn      setText   = (setText_fn)      dlsym(s_h_widgets, "_ZN15QAbstractButton7setTextERK7QString");
    setStyle_fn     setStyle  = (setStyle_fn)     dlsym(s_h_widgets, "_ZN7QWidget13setStyleSheetERK7QString");
    show_fn         w_show    = (show_fn)         dlsym(s_h_widgets, "_ZN7QWidget4showEv");
    raise_fn        w_raise   = (raise_fn)        dlsym(s_h_widgets, "_ZN7QWidget5raiseEv");
    qstring_ctor_fn qs_ctor   = (qstring_ctor_fn) dlsym(s_h_core, "_ZN7QStringC1EPKc");
    if (!qs_ctor) qs_ctor     = (qstring_ctor_fn) dlsym(s_h_core, "_ZN7QStringC2EPKc");
    qstring_from_utf8_fn qs_fromUtf8 = (qstring_from_utf8_fn) dlsym(s_h_core, "_ZN7QString15fromUtf8_helperEPKci");
    qstring_dtor_fn qs_dtor   = (qstring_dtor_fn) dlsym(s_h_core, "_ZN7QStringD1Ev");
    if (!qs_dtor) qs_dtor     = (qstring_dtor_fn) dlsym(s_h_core, "_ZN7QStringD2Ev");

    if (s_log) fprintf(stderr, "[zoffset-2b] syms: ctor=%p geom=%p text=%p style=%p show=%p qs_ctor=%p qs_fromUtf8=%p\n",
                       ctor, setGeomR, setText, setStyle, w_show, qs_ctor, qs_fromUtf8);
    if (!ctor || !w_show) { if (s_log) fprintf(stderr, "[zoffset-2b] essential symbol missing; abort\n"); return; }

    // Allocate; K3SysUi uses 40 bytes for QtCSquareBtn (a QPushButton subclass)
    // so sizeof(QPushButton) <= 40. 64 leaves comfortable headroom.
    void* btn = calloc(1, 64);
    if (!btn) return;

    // Parent to top-level main window (always visible coordinate space).
    // Auto-hide on non-print pages is a future refinement; needs event-filter
    // on a print-page widget to mirror its visibility.
    g_jmp_armed = 1;
    if (sigsetjmp(g_jmp, 1) != 0) {
        if (s_log) fprintf(stderr, "[zoffset-2b] SEGV constructing QPushButton; abort\n");
        g_jmp_armed = 0; free(btn); return;
    }
    ctor(btn, topwidget);
    g_jmp_armed = 0;
    if (s_log) fprintf(stderr, "[zoffset-2b] constructed new QPushButton at %p (parent=%p)\n", btn, topwidget);

    // Inherit geometry from K3SysUi's own (hidden) id=10 button if it set one.
    // Anycubic's setGeometry call places the button where it was originally
    // designed to live; we just copy that placement.
    typedef int (*int_getter_fn)(const void* this_);
    int_getter_fn w_x      = (int_getter_fn) dlsym(s_h_widgets, "_ZNK7QWidget1xEv");
    int_getter_fn w_y      = (int_getter_fn) dlsym(s_h_widgets, "_ZNK7QWidget1yEv");
    int_getter_fn w_width  = (int_getter_fn) dlsym(s_h_widgets, "_ZNK7QWidget5widthEv");
    int_getter_fn w_height = (int_getter_fn) dlsym(s_h_widgets, "_ZNK7QWidget6heightEv");

    int x=120, y=120, w=50, h=50;
    if (w_x && w_y && w_width && w_height) {
        g_jmp_armed = 1;
        if (sigsetjmp(g_jmp, 1) == 0) {
            int tx = w_x(template_btn);
            int ty = w_y(template_btn);
            int tw = w_width(template_btn);
            int th = w_height(template_btn);
            if (s_log) fprintf(stderr, "[zoffset-2b] template geometry: x=%d y=%d w=%d h=%d\n", tx, ty, tw, th);
            if (tw > 0 && th > 0 && tx >= 0 && ty >= 0) { x = tx; y = ty; w = tw; h = th; }
        }
        g_jmp_armed = 0;
    }

    int rect[4] = { x, y, x + w - 1, y + h - 1 };
    g_jmp_armed = 1;
    if (sigsetjmp(g_jmp, 1) == 0 && setGeomR) setGeomR(btn, rect);
    g_jmp_armed = 0;
    if (s_log) fprintf(stderr, "[zoffset-2b] new button placed at (%d,%d) %dx%d\n", x, y, w, h);

    // Icon from the Z-offset SVG that Anycubic already shipped in the Qt
    // resource bundle. Replaces the gray default styling with the asset that
    // was always meant for this button.
    typedef void* (*qicon_ctor_str_fn)(void* this_, const void* qstring_ref);
    typedef void  (*qicon_dtor_fn)(void* this_);
    typedef void  (*setIcon_fn)(void* this_, const void* qicon_ref);
    qicon_ctor_str_fn qicon_ctor = (qicon_ctor_str_fn) dlsym(s_h_widgets, "_ZN5QIconC1ERK7QString");
    if (!qicon_ctor) qicon_ctor  = (qicon_ctor_str_fn) dlsym(s_h_widgets, "_ZN5QIconC2ERK7QString");
    qicon_dtor_fn     qicon_dtor = (qicon_dtor_fn)     dlsym(s_h_widgets, "_ZN5QIconD1Ev");
    if (!qicon_dtor) qicon_dtor  = (qicon_dtor_fn)     dlsym(s_h_widgets, "_ZN5QIconD2Ev");
    setIcon_fn        setIcon    = (setIcon_fn)        dlsym(s_h_widgets, "_ZN15QAbstractButton7setIconERK5QIcon");
    if (s_log) fprintf(stderr, "[zoffset-2b] icon syms: qicon_ctor=%p qicon_dtor=%p setIcon=%p\n", qicon_ctor, qicon_dtor, setIcon);

    typedef bool (*qicon_isnull_fn)(const void* this_);
    typedef void (*set_iconsize_fn)(void* this_, const int* qsize2);
    qicon_isnull_fn qicon_isnull = (qicon_isnull_fn) dlsym(s_h_widgets, "_ZNK5QIcon6isNullEv");
    set_iconsize_fn setIconSize  = (set_iconsize_fn) dlsym(s_h_widgets, "_ZN15QAbstractButton11setIconSizeERK5QSize");

    if (qs_fromUtf8 && qicon_ctor && setIcon) {
        const char* paths[] = {
            ":/FilePrintPage/Zoffset_Item.svg",
            ":/FilePrintPage/Pause-nor.png",  // known-good PNG fallback for diagnostic
            0
        };
        for (int i = 0; paths[i]; i++) {
            char qs[8] = {0};
            char qi[8] = {0};
            int  is_null = 1;
            g_jmp_armed = 1;
            if (sigsetjmp(g_jmp, 1) == 0) {
                // fromUtf8_helper (the exported helper) asserts size != -1;
                // only the inline fromUtf8() wrapper handles the -1 sentinel.
                int slen = (int)strlen(paths[i]);
                qs_fromUtf8(qs, paths[i], slen);
                qicon_ctor(qi, qs);
                if (qicon_isnull) is_null = qicon_isnull(qi) ? 1 : 0;
                if (s_log) fprintf(stderr, "[zoffset-2b] icon[%s] isNull=%d\n", paths[i], is_null);
                if (!is_null) {
                    setIcon(btn, qi);
                    int qsize[2] = { 40, 40 };
                    if (setIconSize) setIconSize(btn, qsize);
                    if (s_log) fprintf(stderr, "[zoffset-2b] applied icon %s + iconSize(40,40)\n", paths[i]);
                }
                if (qicon_dtor) qicon_dtor(qi);
                if (qs_dtor) qs_dtor(qs);
            }
            g_jmp_armed = 0;
            if (!is_null) break;
        }
    }

    // Show and add to group with id=10 (group routing is a backup)
    g_jmp_armed = 1;
    if (sigsetjmp(g_jmp, 1) == 0) {
        w_show(btn);
        if (w_raise) w_raise(btn);
        if (s_real_addButton) s_real_addButton(group, btn, 10);
        if (s_log) fprintf(stderr, "[zoffset-2b] new button %p shown + addButton(group=%p,id=10) done\n", btn, group);
    } else {
        if (s_log) fprintf(stderr, "[zoffset-2b] SEGV during show/addButton; partial inject\n");
    }
    g_jmp_armed = 0;

    // Visibility mirror: install a Qt event filter on the template button
    // that forwards Show/Hide events to our button via setVisible. We avoid
    // the moc requirement by constructing a bare QObject and replacing its
    // per-instance vtable[6] (QObject::eventFilter) with our C function.
    typedef void* (*qobject_ctor_fn)(void* this_, void* parent);
    typedef void  (*install_filter_fn)(void* this_, void* filter);
    qobject_ctor_fn   qobject_ctor   = (qobject_ctor_fn)   dlsym(s_h_core,    "_ZN7QObjectC1EPS_");
    if (!qobject_ctor) qobject_ctor   = (qobject_ctor_fn)   dlsym(s_h_core,    "_ZN7QObjectC2EPS_");
    install_filter_fn installFilter  = (install_filter_fn) dlsym(s_h_core,    "_ZN7QObject18installEventFilterEPS_");
    // We'll need setVisible to call from our event filter
    static setVisible_fn s_setVisible = 0;
    if (!s_setVisible) s_setVisible = (setVisible_fn) dlsym(s_h_widgets, "_ZN7QWidget10setVisibleEb");
    if (s_log) fprintf(stderr, "[zoffset-2b] mirror syms: qobject_ctor=%p installFilter=%p setVisible=%p\n",
                       qobject_ctor, installFilter, s_setVisible);

    if (qobject_ctor && installFilter && s_setVisible) {
        // Allocate space for the QObject. sizeof(QObject) is small (vtable+d_ptr=8).
        void* filter_obj = calloc(1, 32);
        if (filter_obj) {
            g_jmp_armed = 1;
            if (sigsetjmp(g_jmp, 1) == 0) {
                qobject_ctor(filter_obj, 0); // parent=null
                if (s_log) fprintf(stderr, "[zoffset-2b] constructed event-filter QObject at %p\n", filter_obj);

                // Allocate a per-instance vtable copy and patch eventFilter at index 6
                void** old_vt = *(void***)filter_obj;
                void** new_vt = (void**)malloc(sizeof(void*) * 12);
                for (int i = 0; i < 12; i++) new_vt[i] = old_vt[i];

                new_vt[6] = (void*)zoffset_eventFilter;

                // Stash our button pointer right after the QObject so the filter
                // can find it without globals. filter_obj+8 is the d_ptr slot;
                // we put a pointer to our button at offset 16 (past d_ptr).
                *(void**)((char*)filter_obj + 16) = btn;

                *(void***)filter_obj = new_vt;

                // Register first 4 ancestors of template_btn. The page widget
                // is always close to its children; higher ancestors (MainWindow,
                // QStackedWidget root) fire Show only once at boot, which would
                // be false positives. 4 levels covers known cases.
                void* cur = template_btn;
                for (int hops = 0; hops < 4; hops++) {
                    if (s_ancestor_count < 64) {
                        s_ancestors[s_ancestor_count].ancestor  = cur;
                        s_ancestors[s_ancestor_count].button    = btn;
                        s_ancestors[s_ancestor_count].seen_hide = 0;
                        s_ancestor_count++;
                        if (s_log) fprintf(stderr, "[zoffset-2b] registered ancestor[%d]=%p -> btn=%p\n",
                                           s_ancestor_count - 1, cur, btn);
                    }
                    void** w = (void**)cur;
                    void*  d = w[1];
                    if (!d) break;
                    void* p = ((void**)d)[2];
                    if ((uintptr_t)p < 0x10000) break;
                    cur = p;
                }

                // Install the global filter on qApp once.
                static int global_installed = 0;
                if (!global_installed) {
                    static void** s_app_self = 0;
                    if (!s_app_self) s_app_self = (void**) dlsym(s_h_core, "_ZN16QCoreApplication4selfE");
                    void* qapp = s_app_self ? *s_app_self : 0;
                    if (qapp) {
                        installFilter(qapp, filter_obj);
                        global_installed = 1;
                        if (s_log) fprintf(stderr, "[zoffset-2b] GLOBAL event filter installed on qApp=%p\n", qapp);
                    }
                }

                // Start the button HIDDEN. K3SysUi boots on the home page,
                // so the button should not appear until the user navigates to
                // the print page, at which point the event filter on level 1
                // (template_btn->parent) catches ShowToParent and shows it.
                s_setVisible(btn, false);
                if (s_log) fprintf(stderr, "[zoffset-2b] initial visibility set to false (filter will show on Show events)\n");
            } else {
                if (s_log) fprintf(stderr, "[zoffset-2b] SEGV during event filter install\n");
                free(filter_obj);
            }
            g_jmp_armed = 0;
        }
    }

    // PRIMARY routing: connect button->clicked() directly to popup->show()
    // via Qt's string-based connect. Bypasses QButtonGroup entirely.
    //   QMetaObject::Connection QObject::connect(
    //       const QObject *sender, const char *signal,
    //       const QObject *receiver, const char *member,
    //       Qt::ConnectionType type = Qt::AutoConnection)
    // QMetaObject::Connection has a non-trivial dtor, so on ARM EABI it's
    // returned via sret: a hidden result-pointer comes BEFORE the real args.
    // Actual ABI: (result*, sender, signal, recv, slot, type) - 6 args.
    typedef void (*connect_str_fn)(void* result_storage,
                                   const void* sender, const char* signal,
                                   const void* receiver, const char* member, int connType);
    connect_str_fn connectStr = (connect_str_fn)
        dlsym(s_h_core, "_ZN7QObject7connectEPKS_PKcS1_S3_N2Qt14ConnectionTypeE");
    if (s_log) fprintf(stderr, "[zoffset-2b] connectStr=%p, MainWindow=%p\n", connectStr, s_mainwindow);
    if (connectStr && s_mainwindow) {
        void* popup = 0;
        g_jmp_armed = 1;
        if (sigsetjmp(g_jmp, 1) == 0) {
            popup = *(void**)((char*)s_mainwindow + s_popup_offset);
        }
        g_jmp_armed = 0;
        if (s_log) fprintf(stderr, "[zoffset-2b] popup widget = %p\n", popup);
        if ((uintptr_t)popup >= 0x10000) {
            // QMetaObject::Connection is sizeof(void*) == 4 (single d_ptr member).
            // Allocate 8 for slack and zero-init.
            char conn_storage[8] = {0};
            g_jmp_armed = 1;
            if (sigsetjmp(g_jmp, 1) == 0) {
                // QAbstractButton::clicked(bool checked = false) - full sig required
                connectStr(conn_storage, btn, "2clicked(bool)", popup, "1show()", 0 /*AutoConnection*/);
                void* conn_d = *(void**)conn_storage;
                if (s_log) fprintf(stderr, "[zoffset-2b] direct connect btn->clicked => popup->show() conn.d_ptr=%p\n", conn_d);
            } else {
                if (s_log) fprintf(stderr, "[zoffset-2b] SEGV during string-based connect\n");
            }
            g_jmp_armed = 0;
        }
    }
}

// Un-hide a captured id=10 button: show + raise + place at a known location.
static void unhide_button(void* btn) {
    resolve_qt();
    if (!s_h_widgets) { if (s_log) fprintf(stderr, "[zoffset-2b] no Qt handle; cannot unhide\n"); return; }

    setVisible_fn   setVisible = (setVisible_fn)   dlsym(s_h_widgets, "_ZN7QWidget10setVisibleEb");
    show_fn         widget_show = (show_fn)        dlsym(s_h_widgets, "_ZN7QWidget4showEv");
    raise_fn        widget_raise= (raise_fn)       dlsym(s_h_widgets, "_ZN7QWidget5raiseEv");
    setGeomRect_fn  setGeomR   = (setGeomRect_fn)  dlsym(s_h_widgets, "_ZN7QWidget11setGeometryERK5QRect");

    if (s_log) fprintf(stderr, "[zoffset-2b] unhide btn=%p: setVisible=%p show=%p raise=%p setGeomR=%p\n",
                       btn, setVisible, widget_show, widget_raise, setGeomR);

    // QRect in Qt 5 is { int x1, y1, x2, y2 } where x2 = x+w-1, y2 = y+h-1.
    // Place the button at (30, 30) with size 100x100 -> { 30, 30, 129, 129 }.
    int rect[4] = { 120, 120, 120 + 50 - 1, 120 + 50 - 1 };

    g_jmp_armed = 1;
    if (sigsetjmp(g_jmp, 1) == 0) {
        if (setGeomR)   setGeomR(btn, rect);
        if (setVisible) setVisible(btn, true);
        if (widget_show) widget_show(btn);
        if (widget_raise) widget_raise(btn);
        if (s_log) fprintf(stderr, "[zoffset-2b] btn=%p un-hidden (rect set via QRect overload)\n", btn);
    } else {
        if (s_log) fprintf(stderr, "[zoffset-2b] SEGV un-hiding btn=%p; skipping\n", btn);
    }
    g_jmp_armed = 0;
}

// SIGUSR1: replicate dispatcher case 10's popup show.
//   popup_ptr = *(MainWindow + 0x530)
//   popup_ptr->show()
//   popup_ptr->raise()
// If the popup appears, the click-through-signal path is what's broken.
static void on_sigusr1(int) {
    if (!s_mainwindow) {
        fprintf(stderr, "[zoffset-2b] SIGUSR1: no MainWindow saved\n");
        return;
    }
    fprintf(stderr, "[zoffset-2b] SIGUSR1: attempting popup->show() via MainWindow+0x%x\n", s_popup_offset);
    g_jmp_armed = 1;
    if (sigsetjmp(g_jmp, 1) != 0) {
        fprintf(stderr, "[zoffset-2b] SIGUSR1: SEGV reading popup ptr\n");
        g_jmp_armed = 0; return;
    }
    void* popup = *(void**)((char*)s_mainwindow + s_popup_offset);
    g_jmp_armed = 0;
    fprintf(stderr, "[zoffset-2b] SIGUSR1: popup_ptr at MainWindow+0x%x = %p\n", s_popup_offset, popup);
    if ((uintptr_t)popup < 0x10000) { fprintf(stderr, "[zoffset-2b] SIGUSR1: implausible popup ptr\n"); return; }

    resolve_qt();
    if (!s_h_widgets) { fprintf(stderr, "[zoffset-2b] SIGUSR1: no Qt handle\n"); return; }
    show_fn  ws = (show_fn)  dlsym(s_h_widgets, "_ZN7QWidget4showEv");
    raise_fn wr = (raise_fn) dlsym(s_h_widgets, "_ZN7QWidget5raiseEv");
    g_jmp_armed = 1;
    if (sigsetjmp(g_jmp, 1) == 0) {
        if (ws) ws(popup);
        if (wr) wr(popup);
        fprintf(stderr, "[zoffset-2b] SIGUSR1: show()+raise() invoked on popup=%p\n", popup);
    } else {
        fprintf(stderr, "[zoffset-2b] SIGUSR1: SEGV during show()\n");
    }
    g_jmp_armed = 0;
}

// Event filter installed on the K3SysUi template button. Layout:
//   filter_obj+0:  vtable* (our patched copy)
//   filter_obj+4:  d_ptr (real QObject d_ptr)
//   filter_obj+16: our injected button pointer (stashed by injector)
//
// QEvent layout (Qt 5):
//   +0: vtable*
//   +4: d (QEventPrivate*)
//   +8: t (ushort, the event type)
//
// QEvent::Type values: Show=17, Hide=18
// Discovery global event filter. Logs Show/Hide events for every widget in the
// process to identify the widget(s) that toggle on print-page transitions.
extern "C" bool zoffset_eventFilter(void* this_obj, void* watched, void* event) {
    if (!event || !watched) return false;
    unsigned short t = *(unsigned short*)((char*)event + 8);

    // Only Show (17) and Hide (18); match against registered ancestors.
    if (t != 17 && t != 18) return false;

    for (int i = 0; i < s_ancestor_count; i++) {
        if (s_ancestors[i].ancestor != watched) continue;

        typedef void (*setvis_fn)(void*, bool);
        static setvis_fn setvis = 0;
        if (!setvis) {
            void* h = dlopen("libQt5Widgets.so.5", RTLD_LAZY | RTLD_LOCAL);
            if (h) setvis = (setvis_fn) dlsym(h, "_ZN7QWidget10setVisibleEb");
        }
        if (!setvis) return false;

        bool visible = (t == 17);
        setvis(s_ancestors[i].button, visible);
        fprintf(stderr, "[zoffset-2b] ancestor %s on %p -> setVisible(%d) on btn=%p\n",
                visible ? "SHOW" : "HIDE", watched, (int)visible, s_ancestors[i].button);
        break;
    }
    return false;
}

__attribute__((visibility("default")))
void _ZN12QButtonGroup9addButtonEP15QAbstractButtoni(void* self, void* button, int id) {
    if (!s_real_addButton) {
        s_real_addButton = (addButton_fn) dlsym(RTLD_NEXT, "_ZN12QButtonGroup9addButtonEP15QAbstractButtoni");
    }
    if (!s_real_addButton) return;

    s_real_addButton(self, button, id);

    if (!s_log && !s_unhide) return;

    s_call_count++;
    if (s_log) fprintf(stderr, "[zoffset-2b] #%d addButton(group=%p, btn=%p, id=%d)\n",
                       s_call_count, self, button, id);

    GroupTrack* t = track_find_or_new(self);
    if (!t) return;

    // Track strict 0..9 sequence (the print-page button-construction loop).
    // After id=9 increments next_id to 10, the next addButton(id=10) is the
    // existing K3SysUi-built button we want to capture and un-hide.
    if (id == 0) {
        t->next_id = 1;
        t->got9 = 0;
    } else if (id == t->next_id) {
        t->next_id++;
        if (id == 9) {
            t->got9 = 1;
            if (s_log) fprintf(stderr, "[zoffset-2b] group=%p completed 0..9 (print-page candidate)\n", self);
        } else if (id == 10 && t->got9 && s_id10_count < MAX_TRACKS) {
            s_id10_buttons[s_id10_count++] = button;
            if (s_log) fprintf(stderr, "[zoffset-2b] captured existing id=10 button on print-page group=%p btn=%p (#%d total)\n",
                               self, button, s_id10_count);
            if (s_unhide) unhide_button(button);
            if (s_inject) inject_new_button(self, button);
        }
    } else if (id < t->next_id || id > 12) {
        t->next_id = 0; t->got9 = 0;
    }
}

} // extern "C"

__attribute__((constructor))
static void rinkhals_zoffset_init(void) {
    setvbuf(stderr, 0, _IOLBF, 0);
    const char* l = getenv("RINKHALS_ZOFFSET_LOG");
    const char* u = getenv("RINKHALS_ZOFFSET_UNHIDE");
    const char* i = getenv("RINKHALS_ZOFFSET_INJECT");
    s_log    = (l && l[0] == '1');
    s_unhide = (u && u[0] == '1');
    s_inject = (i && i[0] == '1');
    if (s_log || s_unhide || s_inject) {
        struct sigaction sa = {};
        sa.sa_handler = segv_handler;
        sa.sa_flags = SA_NODEFER;
        sigaction(SIGSEGV, &sa, 0);
        struct sigaction su = {};
        su.sa_handler = on_sigusr1;
        sigaction(SIGUSR1, &su, 0);
        fprintf(stderr, "[zoffset-2b] loaded pid=%d (log=%d unhide=%d inject=%d) SIGUSR1=popup-show\n",
                (int)getpid(), s_log, s_unhide, s_inject);

        // Discover Anycubic-specific offsets from the K3SysUi binary now so
        // subsequent uses pick up the discovered value (or fall back gracefully).
        discover_offsets();
    }
    memset(s_tracks, 0, sizeof(s_tracks));
    memset(s_id10_buttons, 0, sizeof(s_id10_buttons));
    s_id10_count = 0;
}
