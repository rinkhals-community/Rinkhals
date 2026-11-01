#!/bin/sh

# Used by main Dockerfile

set -e

WORK=$(mktemp -d)
trap "rm -rf $WORK" EXIT
cd "$WORK"

FILES_DIR="${FILES_DIR:-/files}"

MOONRAKER_COMMIT=3c1f31874ac0beba35747059637583e5d2c383c0
MOONRAKER_DIRECTORY=$FILES_DIR/4-apps/home/rinkhals/apps/40-moonraker

echo "Downloading Moonraker..."
wget -O moonraker.zip https://github.com/Arksine/moonraker/archive/${MOONRAKER_COMMIT}.zip
unzip -d moonraker moonraker.zip

mkdir -p $MOONRAKER_DIRECTORY/moonraker
rm -rf $MOONRAKER_DIRECTORY/moonraker/*
cp -pr "$WORK"/moonraker/*/* $MOONRAKER_DIRECTORY/moonraker

# Apply Rinkhals spoolman compatibility fix directly in Moonraker source.
# See: https://github.com/utkabobr/DuckPro-Kobra3/issues/54#issuecomment-2540040852
SPOOLMAN_FILE="$MOONRAKER_DIRECTORY/moonraker/moonraker/components/spoolman.py"
if [ -f "$SPOOLMAN_FILE" ] && ! grep -q "SPOOL_ID: Union\[int, None\]" "$SPOOLMAN_FILE"; then
	perl -0pi -e 's/def set_active_spool\(self, spool_id: Union\[int, None\]\) -> None:\n        assert spool_id is None or isinstance\(spool_id, int\)/def set_active_spool(self, spool_id: Union[int, None] = None, SPOOL_ID: Union[int, None] = None) -> None:\n        if spool_id is None and SPOOL_ID is not None:\n            spool_id = int(str(SPOOL_ID).lstrip("="))\n        assert spool_id is None or isinstance(spool_id, int)/' "$SPOOLMAN_FILE"

	# Fail loudly rather than shipping an unpatched spoolman.py. The perl
	# substitution matches an exact two-line pattern, so a MOONRAKER_COMMIT bump
	# or any upstream reformatting would silently match nothing and exit 0 -
	# and the M555 SPOOL_ID handling this patch exists for would quietly
	# regress, to be discovered by a user rather than by the build.
	if ! grep -q "SPOOL_ID: Union\[int, None\]" "$SPOOLMAN_FILE"; then
		echo "ERROR: spoolman.py SPOOL_ID patch did not apply - did upstream Moonraker change set_active_spool?" >&2
		exit 1
	fi
fi

# GoKlipper sends some notifications with the remote method in
# template.method instead of the top-level method field expected by Moonraker.
# Normalize registered template methods so G-code responses reach clients.
KLIPPY_CONNECTION_FILE="$MOONRAKER_DIRECTORY/moonraker/moonraker/components/klippy_connection.py"
if [ -f "$KLIPPY_CONNECTION_FILE" ] && ! grep -q "GoKlipper compatibility" "$KLIPPY_CONNECTION_FILE"; then
	perl -0pi -e 's/        method = cmd\.get\('"'"'method'"'"', None\)\n        if method is not None:/        method = cmd.get('"'"'method'"'"', None)\n\n        # GoKlipper compatibility: some notifications put the remote method\n        # in template.method rather than the top-level method field.\n        # Only for messages without an id: a reply to a request also lacks a\n        # top-level method, and must never be dispatched as a notification.\n        if method is None and cmd.get('"'"'id'"'"') is None:\n            template = cmd.get('"'"'template'"'"')\n            if isinstance(template, dict):\n                template_method = template.get('"'"'method'"'"')\n                params = cmd.get('"'"'params'"'"', {})\n                if (\n                    template_method in self.remote_methods and\n                    isinstance(params, dict)\n                ):\n                    self.event_loop.register_callback(\n                        self._execute_method, template_method, **params)\n                    return\n\n        if method is not None:/' "$KLIPPY_CONNECTION_FILE"

	if ! grep -q "GoKlipper compatibility" "$KLIPPY_CONNECTION_FILE"; then
		echo "ERROR: klippy_connection.py GoKlipper compatibility patch did not apply - did upstream Moonraker change _process_command?" >&2
		exit 1
	fi
fi

# Keep temporary-file uploads atomic when Moonraker's temp directory and the
# destination are on different filesystems.  shutil.move() falls back to
# copy/delete on EXDEV and truncates an existing destination in place.
FILE_MANAGER="$MOONRAKER_DIRECTORY/moonraker/moonraker/components/file_manager/file_manager.py"
if [ -f "$FILE_MANAGER" ] && ! grep -q "def _atomic_move_file" "$FILE_MANAGER"; then
	sed -i '/^import os$/a import errno' "$FILE_MANAGER"

	sed -i '/^    def _zip_files(/i\
    @staticmethod\
    def _atomic_move_file(source: StrOrPath, destination: StrOrPath) -> None:\
        source = pathlib.Path(source)\
        destination = pathlib.Path(destination)\
        try:\
            os.replace(source, destination)\
            return\
        except OSError as e:\
            if e.errno != errno.EXDEV:\
                raise\
\
        temp_path: Optional[pathlib.Path] = None\
        try:\
            with tempfile.NamedTemporaryFile(\
                dir=str(destination.parent),\
                prefix=f".{destination.name}.",\
                suffix=".tmp",\
                delete=False\
            ) as temp_file:\
                temp_path = pathlib.Path(temp_file.name)\
                with source.open("rb") as src_file:\
                    shutil.copyfileobj(src_file, temp_file)\
                temp_file.flush()\
                os.fsync(temp_file.fileno())\
\
            shutil.copystat(source, temp_path)\
            os.replace(temp_path, destination)\
            temp_path = None\
            source.unlink()\
        finally:\
            if temp_path is not None:\
                with contextlib.suppress(OSError):\
                    temp_path.unlink()\
' "$FILE_MANAGER"

	sed -i 's|        shutil.move(str(temp_dest), str(destination))|        self._atomic_move_file(temp_dest, destination)|' "$FILE_MANAGER"
	sed -i "/                shutil.move(/ {N; s|                shutil.move(\\n                    upload_info\\['tmp_file_path'\\], dest_path)|                self._atomic_move_file(upload_info['tmp_file_path'], dest_path)|;}" "$FILE_MANAGER"
fi

# Fail the build if a Moonraker update or reformatting makes the compatibility
# patch miss.  This patch is intentionally tied to the pinned Moonraker source
# and can be removed once the pinned revision contains the upstream fix.
if ! grep -q "^import errno$" "$FILE_MANAGER" ||
   ! grep -q "def _atomic_move_file" "$FILE_MANAGER" ||
   ! grep -q "self._atomic_move_file(temp_dest, destination)" "$FILE_MANAGER" ||
   ! grep -q "self._atomic_move_file(upload_info\\['tmp_file_path'\\], dest_path)" "$FILE_MANAGER"; then
	echo "ERROR: Moonraker atomic temp-file move patch did not apply - did upstream file_manager.py change?" >&2
	exit 1
fi

VERSION=$(echo $MOONRAKER_COMMIT | cut -c1-7)
sed -i "s/\"version\": *\"[^\"]*\"/\"version\": \"${VERSION}\"/" $MOONRAKER_DIRECTORY/app.json
