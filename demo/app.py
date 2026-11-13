import gradio as gr
from openai_settings import resolve_openai_settings
import subprocess, shutil, os, zipfile, datetime, sys, time, uuid, stat, re
from pathlib import Path
import base64


# =====================
# Version guard
# =====================
def _ensure_versions():
    import importlib, subprocess, sys

    def get_version(pkg):
        try:
            m = importlib.import_module(pkg)
            return getattr(m, "__version__", "0")
        except Exception:
            return "0"

    try:
        from packaging.version import Version
    except ImportError:
        # 安装packaging，确保下面版本比较能用
        subprocess.check_call([sys.executable, "-m", "pip", "install", "packaging"])
        from packaging.version import Version

    # 检查 huggingface_hub
    hub_ver = get_version("huggingface_hub")
    hv = Version(hub_ver)

    required_min = Version("0.24.0")
    required_max = Version("1.0.0")

    hub_ok = required_min <= hv < required_max

    if not hub_ok:
        print(f"[INFO] huggingface_hub=={hub_ver} not in range "
              f"[{required_min}, {required_max}), reinstalling...")
        subprocess.check_call([
            sys.executable, "-m", "pip", "install",
            "huggingface-hub==0.27.1",
            "transformers==4.48.0",
            "--force-reinstall", "--no-deps"
        ])
    else:
        print(f"[INFO] huggingface_hub version OK: {hub_ver}")

_ensure_versions()

# =====================
# Paths (read-only repo root; DO NOT write here)
# =====================
ROOT = Path(__file__).resolve().parent
RUNS_DIR = ROOT / "runs"              # all per-run workspaces live here
RUNS_DIR.mkdir(parents=True, exist_ok=True)

TIMEOUT_SECONDS = 1800  # 30 minutes
RETENTION_HOURS = 1    # auto-clean runs older than N hours
DEFAULT_RIGHT_LOGO_PATH = ROOT / "template" / "logos" / "right_logo.png"

# ---------------------
# Utils
# ---------------------
def _now_str():
    return datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

def _write_logs(log_path: Path, logs):
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "w", encoding="utf-8") as f:
            f.write("\n".join(logs))
    except Exception:
        pass

def _find_ui_header_logos(root: Path):
    """Return list of Paths for UI header logos in order camel → tvg → waterloo.
    Prefer template/logos; fallback to assets folders; if none match, return up to 3 images.
    """
    preferred = root / "template" / "logos"
    # Desired visual order (left → right) with CAMEL at rightmost:
    names = ["tvg", "waterloo", "camel"]
    found = []
    # Try preferred dir first with explicit names
    try:
        if preferred.exists():
            allp = list(preferred.iterdir())
            for key in names:
                for p in allp:
                    if p.is_file() and p.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"} and key in p.name.lower():
                        found.append(p)
                        break
    except Exception:
        pass
    # If not all found, search broader locations
    if len(found) < 3:
        cand_dirs = [
            root / "assets",
            root / "assets" / "logos",
            root / "Paper2Poster" / "assets",
            root / "Paper2Poster" / "assets" / "logos",
            root / "paper2poster" / "assets",
            root / "paper2poster" / "assets" / "logos",
        ]
        imgs = []
        for d in cand_dirs:
            try:
                if d.exists():
                    for p in d.iterdir():
                        if p.is_file() and p.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
                            imgs.append(p)
            except Exception:
                continue
        for key in names:
            if any(key in str(fp).lower() for fp in found):
                continue
            for p in imgs:
                if key in p.name.lower():
                    found.append(p)
                    break
        # Fallback: fill up to 3
        if not found and imgs:
            found = imgs[:3]
    return found

def _ui_header_logos_html():
    """Return an HTML div with base64-embedded logos to avoid broken /file routes.
    Logos are fixed at top-right, slightly inset, with larger spacing.
    """
    import base64
    logos = _find_ui_header_logos(ROOT)
    if not logos:
        return ""
    parts = []
    for p in logos:
        try:
            b = p.read_bytes()
            b64 = base64.b64encode(b).decode("utf-8")
            mime = "image/png" if p.suffix.lower() == ".png" else "image/jpeg"
            src = f"data:{mime};base64,{b64}"
            name = p.name.lower()
            href = None
            if "camel" in name:
                href = "https://www.camel-ai.org/"
            elif "tvg" in name or "torr" in name:
                href = "https://torrvision.com/index.html"
            elif "waterloo" in name:
                href = "https://uwaterloo.ca/"
            img = f"<img src='{src}' alt='{p.stem}' style='height:44px;width:auto;object-fit:contain;display:block;cursor:pointer'>"
            parts.append(f"<a href='{href}' target='_blank' rel='noopener'>{img}</a>" if href else img)
        except Exception:
            continue
    if not parts:
        return ""
    # Fixed-position header bar at top-right; moved further left and larger spacing
    imgs = "".join(parts)
    return (
        "<style>"
        "#p2p-logo-bar{position:fixed;top:12px;right:140px;display:flex;gap:24px;"
        "align-items:center;z-index:9999}"
        "#p2p-logo-bar a{display:block;line-height:0}"
        "@media (max-width: 768px){#p2p-logo-bar img{height:32px}}"
        "</style>"
        "<div id='p2p-logo-bar'>" + imgs + "</div>"
    )

def _default_conf_logo_path():
    """Pick a default conference logo to preview.
    Prefer Paper2Poster/assets/neurips.png, else template/logos/right_logo.png,
    else the first of detected header logos.
    """
    try:
        prefer_assets = ROOT / "Paper2Poster" / "assets" / "neurips.png"
        if prefer_assets.exists():
            return prefer_assets
        pref = ROOT / "template" / "logos" / "right_logo.png"
        if pref.exists():
            return pref
        logos = _find_ui_header_logos(ROOT)
        for p in logos:
            if p and p.exists():
                return p
    except Exception:
        pass
    return None

## Removed sanitizer per request: do not mutate user-generated TeX

def _on_rm_error(func, path, exc_info):
    # fix "PermissionError: [Errno 13] Permission denied" for readonly files
    os.chmod(path, stat.S_IWRITE)
    func(path)

def _copytree(src: Path, dst: Path, symlinks=True, ignore=None):
    if dst.exists():
        shutil.rmtree(dst, onerror=_on_rm_error)
    shutil.copytree(src, dst, symlinks=symlinks, ignore=ignore)

def _safe_copy(src: Path, dst: Path):
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)

def _cleanup_old_runs(max_age_hours=12):
    try:
        now = datetime.datetime.now().timestamp()
        for run_dir in RUNS_DIR.iterdir():
            try:
                if not run_dir.is_dir():
                    continue
                mtime = run_dir.stat().st_mtime
                age_h = (now - mtime) / 3600.0
                if age_h > max_age_hours:
                    shutil.rmtree(run_dir, onerror=_on_rm_error)
            except Exception:
                continue
    except Exception:
        pass

def _prepare_workspace(logs):
    """Create isolated per-run workspace and copy needed code/assets into it."""
    run_id = datetime.datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8]
    work_dir = RUNS_DIR / run_id
    work_dir.mkdir(parents=True, exist_ok=True)

    # Per-run log & zip path
    log_path = work_dir / "run.log"
    zip_path = work_dir / "output.zip"

    logs.append(f"🧩 New workspace: {work_dir.relative_to(ROOT)} (run_id={run_id})")

    # Copy code/assets that do file IO so they are run-local (avoid shared writes)
    # Keep copies as cheap as possible (symlinks=True when supported)
    needed_dirs = ["posterbuilder", "Paper2Poster"]
    for d in needed_dirs:
        src = ROOT / d
        if src.exists():
            _copytree(src, work_dir / d, symlinks=True)
            logs.append(f"   ↪ copied {d}/ → runs/{run_id}/{d}/ (symlink where possible)")

    # template/ optional
    tmpl = ROOT / "template"
    if tmpl.exists():
        _copytree(tmpl, work_dir / "template", symlinks=True)
        logs.append("   ↪ copied template/")

    # pipeline.py must live inside workspace so that ROOT_DIR=work_dir
    _safe_copy(ROOT / "pipeline.py", work_dir / "pipeline.py")
    _safe_copy(ROOT / "openai_settings.py", work_dir / "openai_settings.py")

    # Create standard IO dirs in workspace
    (work_dir / "input" / "pdf").mkdir(parents=True, exist_ok=True)
    (work_dir / "input" / "logo").mkdir(parents=True, exist_ok=True)
    (work_dir / "posterbuilder" / "latex_proj").mkdir(parents=True, exist_ok=True)

    return run_id, work_dir, log_path, zip_path

# ---------------------
# Helpers for new features (post-processing)
# ---------------------
def _parse_rgb(val):
    """Return (R, G, B) as ints in [0,255] from '#RRGGBB', 'rgb(...)', 'rgba(...)', 'r,g,b', [r,g,b], or (r,g,b)."""
    if val is None:
        return None

    import re

    def clamp255(x):
        try:
            return max(0, min(255, int(round(float(x)))))
        except Exception:
            return None

    s = str(val).strip()

    # list/tuple
    if isinstance(val, (list, tuple)) and len(val) >= 3:
        r, g, b = [clamp255(val[0]), clamp255(val[1]), clamp255(val[2])]
        if None not in (r, g, b):
            return (r, g, b)

    # hex: #RGB or #RRGGBB
    if s.startswith("#"):
        hx = s[1:].strip()
        if len(hx) == 3:
            hx = "".join(c*2 for c in hx)
        if len(hx) == 6 and re.fullmatch(r"[0-9A-Fa-f]{6}", hx):
            return tuple(int(hx[i:i+2], 16) for i in (0, 2, 4))

    # rgb/rgba(...)
    m = re.match(r"rgba?\(\s*([^)]+)\)", s, flags=re.IGNORECASE)
    if m:
        parts = [p.strip() for p in m.group(1).split(",")]
        if len(parts) >= 3:
            def to_int(p):
                if p.endswith("%"):
                    # percentage to 0-255
                    return clamp255(float(p[:-1]) * 255.0 / 100.0)
                return clamp255(p)
            r, g, b = to_int(parts[0]), to_int(parts[1]), to_int(parts[2])
            if None not in (r, g, b):
                return (r, g, b)

    # 'r,g,b'
    if "," in s:
        parts = [p.strip() for p in s.split(",")]
        if len(parts) >= 3:
            def to_int(p):
                if p.endswith("%"):
                    return clamp255(float(p[:-1]) * 255.0 / 100.0)
                return clamp255(p)
            r, g, b = to_int(parts[0]), to_int(parts[1]), to_int(parts[2])
            if None not in (r, g, b):
                return (r, g, b)

    return None


def _apply_meeting_logo(OUTPUT_DIR: Path, meeting_logo_file, logs):
    """Replace output/poster_latex_proj/logos/right_logo.png if meeting_logo_file provided."""
    if not meeting_logo_file:
        return False

def _ensure_right_logo_default(OUTPUT_DIR: Path, logs):
    """If no right_logo.png exists in output poster project, copy a default NeurIPS logo.
    Looks for Paper2Poster/assets/neurips.png first, else template/logos/right_logo.png.
    Returns True if a logo was written.
    """
    try:
        logos_dir = OUTPUT_DIR / "poster_latex_proj" / "logos"
        target = logos_dir / "right_logo.png"
        if target.exists():
            return False
        # Preferred default
        prefer_assets = ROOT / "Paper2Poster" / "assets" / "neurips.png"
        fallback_tpl = ROOT / "template" / "logos" / "right_logo.png"
        src = None
        if prefer_assets.exists():
            src = prefer_assets
        elif fallback_tpl.exists():
            src = fallback_tpl
        if src is None:
            logs.append("⚠️ No default right_logo source found (neurips.png or template right_logo.png).")
            return False
        logos_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, target)
        logs.append(f"🏷️ Applied default conference logo → {target.relative_to(OUTPUT_DIR)}")
        return True
    except Exception as e:
        logs.append(f"⚠️ Failed to apply default right_logo: {e}")
        return False

    logos_dir = OUTPUT_DIR / "poster_latex_proj" / "logos"
    target = logos_dir / "right_logo.png"
    try:
        logos_dir.mkdir(parents=True, exist_ok=True)
        # Try to convert to PNG for safety
        try:
            from PIL import Image
            img = Image.open(meeting_logo_file.name)
            # preserve alpha if available
            if img.mode not in ("RGB", "RGBA"):
                img = img.convert("RGBA")
            img.save(target, format="PNG")
            logs.append(f"🖼️ Meeting logo converted to PNG and saved → {target.relative_to(OUTPUT_DIR)}")
        except Exception as e:
            # Fallback: raw copy with .png name
            shutil.copy(meeting_logo_file.name, target)
            logs.append(f"🖼️ Meeting logo copied (no conversion) → {target.relative_to(OUTPUT_DIR)} (note: ensure it's a valid PNG).")
        return True
    except Exception as e:
        logs.append(f"⚠️ Failed to apply meeting logo: {e}")
        return False

def _apply_theme_rgb(OUTPUT_DIR: Path, rgb_tuple, logs):
    if not rgb_tuple:
        return False

    tex_path = OUTPUT_DIR / "poster_latex_proj" / "poster_output.tex"
    if not tex_path.exists():
        logs.append(f"⚠️ Theme RGB skipped: {tex_path.relative_to(OUTPUT_DIR)} not found.")
        return False

    try:
        content = tex_path.read_text(encoding="utf-8")
        r, g, b = rgb_tuple
        name_pattern = r"(?:nipspurple|neuripspurple|themecolor)"

        rgb_pat = rf"(\\definecolor\{{{name_pattern}\}}\{{RGB\}}\{{)\s*\d+\s*,\s*\d+\s*,\s*\d+\s*(\}})"

        def repl_rgb(m):
            return f"{m.group(1)}{r},{g},{b}{m.group(2)}"

        new_content, n = re.subn(rgb_pat, repl_rgb, content, flags=re.MULTILINE)

        if n == 0:
            hexval = f"{r:02X}{g:02X}{b:02X}"
            html_pat = rf"(\\definecolor\{{{name_pattern}\}}\{{HTML\}}\{{)[0-9A-Fa-f]{{6}}(\}})"

            def repl_html(m):
                return f"{m.group(1)}{hexval}{m.group(2)}"

            new_content, n = re.subn(html_pat, repl_html, content, flags=re.MULTILINE)

        if n > 0:
            tex_path.write_text(new_content, encoding="utf-8")
            logs.append(f"🎨 Theme color updated to RGB {{{r},{g},{b}}}")
            return True
        else:
            logs.append("ℹ️ No \\definecolor target found.")
            return False

    except Exception as e:
        logs.append(f"⚠️ Failed to update theme RGB: {e}")
        return False



def _apply_left_logo(OUTPUT_DIR: Path, logo_files, logs):
    """
    Use the first institutional logo uploaded by the user:
    - Copy it into output/poster_latex_proj/logos/ as left_logo.<ext>
    - Replace 'logos/left_logo.png' in poster_output.tex with the proper file extension
    Does NOT convert formats. Simply renames and rewrites the tex reference.
    """
    if not logo_files:
        logs.append("ℹ️ No institutional logo uploaded.")
        return False

    if isinstance(logo_files, (list, tuple)) and len(logo_files) > 1:
        logs.append("Multiple institutional logos uploaded.")
        return False

    # Single file case
    f = logo_files[0] if isinstance(logo_files, (list, tuple)) else logo_files
    if not f:
        logs.append("ℹ️ No institutional logo uploaded.")
        return False

    ext = Path(f.name).suffix or ".png"  # fallback to .png if no extension
    logos_dir = OUTPUT_DIR / "poster_latex_proj" / "logos"
    tex_path = OUTPUT_DIR / "poster_latex_proj" / "poster_output.tex"

    try:
        logos_dir.mkdir(parents=True, exist_ok=True)
        dst = logos_dir / f"left_logo{ext}"
        shutil.copy(f.name, dst)
        logs.append(f"🏷️ Institutional logo copied to: {dst.relative_to(OUTPUT_DIR)}")
    except Exception as e:
        logs.append(f"⚠️ Failed to copy institutional logo: {e}")
        return False

    if not tex_path.exists():
        logs.append("⚠️ poster_output.tex not found, cannot replace left_logo path.")
        return False

    try:
        text = tex_path.read_text(encoding="utf-8")
        old = "logos/left_logo.png"
        new = f"logos/left_logo{ext}"

        if old in text:
            tex_path.write_text(text.replace(old, new), encoding="utf-8")
            logs.append(f"🛠️ Replaced left_logo.png → left_logo{ext} in poster_output.tex")
            return True

        # Fallback (covers weird spacing or macro variations)
        import re
        pattern = r"(logos/left_logo)\.png"
        new_text, n = re.subn(pattern, r"\1" + ext, text)

        if n > 0:
            tex_path.write_text(new_text, encoding="utf-8")
            logs.append(f"🛠️ Replaced left_logo.png → left_logo{ext} (regex fallback)")
            return True

        logs.append("ℹ️ No left_logo.png reference found in poster_output.tex.")
        return False

    except Exception as e:
        logs.append(f"⚠️ Failed to modify poster_output.tex: {e}")
        return False

def render_overleaf_button(overleaf_b64):
    if not overleaf_b64:
        return ""
    
    html = f"""
    <form action="https://www.overleaf.com/docs" method="post" target="_blank">
      <input type="hidden" name="snip_uri" value="data:application/zip;base64,{overleaf_b64}">
      <input type="hidden" name="engine" value="xelatex">
      <button style="
        background:#4CAF50;color:white;padding:8px 14px;
        border:none;border-radius:6px;cursor:pointer; margin-top:8px;
      ">
        🚀 Open in Overleaf
      </button>
    </form>
    """
    return html

def _get_tectonic_bin(logs):
    """Return a usable path to the tectonic binary. Try PATH/common paths; if not found, download to runs/_bin."""
    import shutil as _sh, tarfile, urllib.request, os
    # 1) existing in PATH or common dirs
    cands = [
        "tectonic",
        str(Path("/usr/local/bin/tectonic")),
        str(Path("/usr/bin/tectonic")),
        os.path.expanduser("~/.local/bin/tectonic"),
        str((RUNS_DIR / "_bin" / "tectonic").resolve()),
    ]
    for c in cands:
        if _sh.which(c) or Path(c).exists():
            return c
    # 2) download to runs/_bin
    try:
        url = "https://github.com/tectonic-typesetting/tectonic/releases/download/tectonic%400.15.0/tectonic-0.15.0-x86_64-unknown-linux-gnu.tar.gz"
        bin_dir = RUNS_DIR / "_bin"
        bin_dir.mkdir(parents=True, exist_ok=True)
        tgz = bin_dir / "tectonic.tar.gz"
        logs.append("⬇️ Downloading tectonic binary …")
        with urllib.request.urlopen(url, timeout=60) as resp, open(tgz, "wb") as out:
            out.write(resp.read())
        with tarfile.open(tgz, "r:gz") as tf:
            tf.extractall(path=bin_dir)
        # find binary
        tbin = None
        for p in bin_dir.rglob("tectonic"):
            if p.is_file() and os.access(p, os.X_OK):
                tbin = p
                break
        if not tbin:
            # make executable if needed
            for p in bin_dir.rglob("tectonic"):
                try:
                    p.chmod(0o755)
                    tbin = p
                    break
                except Exception:
                    continue
        if tbin:
            logs.append(f"✅ Tectonic ready at {tbin}")
            return str(tbin)
        logs.append("⚠️ Tectonic binary not found after download.")
    except Exception as e:
        logs.append(f"⚠️ Tectonic download failed: {e}")
    return None

def _compile_poster_pdf(OUTPUT_DIR: Path, logs):
    """
    Compile output/poster_latex_proj/poster_output.tex into a PDF using an
    available TeX engine. Prefer 'tectonic', then 'lualatex', then 'xelatex',
    then 'latexmk'. Returns Path to the PDF or None.
    """
    try:
        proj_dir = OUTPUT_DIR / "poster_latex_proj"
        tex_path = proj_dir / "poster_output.tex"
        if not tex_path.exists():
            logs.append(f"⚠️ LaTeX source not found: {tex_path.relative_to(OUTPUT_DIR)}")
            return None

        # Clean old PDFs
        for cand in (proj_dir / "poster_output.pdf", proj_dir / "poster.pdf"):
            try:
                if cand.exists():
                    cand.unlink()
            except Exception:
                pass

        import shutil as _sh
        import subprocess as _sp

        def _has(bin_name):
            return _sh.which(bin_name) is not None

        # Most-tolerant: prefer latexmk with XeLaTeX and force (-f), then XeLaTeX, then LuaLaTeX
        pretex = r"\nonstopmode\scrollmode\makeatletter\let\pgf@error\pgf@warning\let\GenericError\GenericWarning\let\PackageError\PackageWarning\makeatother"
        if _has("latexmk"):
            cmd = [
                "latexmk", "-pdf", "-pdflatex=xelatex", "-f",
                "-interaction=nonstopmode", "-file-line-error",
                f"-pretex={pretex}",
                tex_path.name,
            ]
            logs.append("▶ Compiling with latexmk (-pdf -pdflatex=xelatex -f, pretex demote errors) …")
        elif _has("xelatex"):
            # Inject pretex macros via direct input to engine (no file mutation)
            injected = pretex + f"\\input{{{tex_path.name}}}"
            cmd = ["xelatex", "-interaction=nonstopmode", "-file-line-error", injected]
            logs.append("▶ Compiling with xelatex (pretex injected) …")
        elif _has("lualatex"):
            injected = pretex + f"\\input{{{tex_path.name}}}"
            cmd = ["lualatex", "-interaction=nonstopmode", "-file-line-error", injected]
            logs.append("▶ Compiling with lualatex (pretex injected) …")
        else:
            logs.append("⚠️ No TeX engine found (latexmk/xelatex/lualatex). Skipping PDF compile.")
            return None

        import os as _os
        _env = _os.environ.copy()
        # Ensure TeX can find local theme/fonts across project tree
        texinputs = _env.get("TEXINPUTS", "")
        search = _os.pathsep.join([
            str(proj_dir), str(proj_dir) + "//",
            str(proj_dir.parent), str(proj_dir.parent) + "//",
        ])
        _env["TEXINPUTS"] = search + _os.pathsep + texinputs
        proc = _sp.run(cmd, cwd=str(proj_dir), stdout=_sp.PIPE, stderr=_sp.STDOUT, text=True, env=_env)
        if proc.stdout:
            logs.append(proc.stdout[-4000:])

        # Accept PDF even if return code is non-zero (be tolerant)
        for out_name in ("poster_output.pdf", "poster.pdf", tex_path.stem + ".pdf"):
            out_path = proj_dir / out_name
            if out_path.exists():
                if proc.returncode != 0:
                    logs.append(f"⚠️ Compile returned code {proc.returncode}, but PDF exists; using it.")
                else:
                    logs.append(f"✅ PDF generated → {out_path.relative_to(OUTPUT_DIR)}")
                return out_path

        if proc.returncode != 0:
            logs.append(f"❌ PDF compile failed with code {proc.returncode} and no PDF produced.")
            return None

        logs.append("⚠️ PDF not found after compile.")
        return None
    except Exception as e:
        logs.append(f"⚠️ PDF compile error: {e}")
        return None

def _pdf_to_iframe_html(pdf_path: Path, width="100%", height="900px") -> str:
    try:
        b = pdf_path.read_bytes()
        b64 = base64.b64encode(b).decode("utf-8")
        return (
            f"<div style='border:1px solid #ddd;border-radius:8px;overflow:hidden'>"
            f"<embed type='application/pdf' width='{width}' height='{height}' src='data:application/pdf;base64,{b64}'></embed>"
            f"</div>"
        )
    except Exception:
        return ""

def _pdf_to_iframe_file(pdf_path: Path, width="100%", height="900px") -> str:
    try:
        from urllib.parse import quote
        p = str(pdf_path)
        src = f"/file={quote(p)}"
        return (
            f"<div style='border:1px solid #ddd;border-radius:8px;overflow:hidden'>"
            f"<iframe src='{src}' width='{width}' height='{height}' style='border:0'></iframe>"
            f"</div>"
        )
    except Exception:
        return ""

def _pdf_to_image_first_page(pdf_path: Path, out_dir: Path, logs) -> Path | None:
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "poster_preview.png"
        # Try PyMuPDF
        try:
            import fitz  # PyMuPDF
            doc = fitz.open(str(pdf_path))
            if doc.page_count == 0:
                return None
            page = doc.load_page(0)
            mat = fitz.Matrix(2, 2)
            pix = page.get_pixmap(matrix=mat, alpha=False)
            pix.save(str(out_path))
            return out_path if out_path.exists() else None
        except Exception as e:
            logs.append(f"⚠️ PyMuPDF render failed: {e}")
        # Fallback: pypdfium2
        try:
            import pypdfium2 as pdfium
            pdf = pdfium.PdfDocument(str(pdf_path))
            if len(pdf) == 0:
                return None
            page = pdf[0]
            bitmap = page.render(scale=2).to_pil()
            bitmap.save(out_path)
            return out_path if out_path.exists() else None
        except Exception as e:
            logs.append(f"⚠️ pypdfium2 render failed: {e}")
    except Exception as e:
        logs.append(f"⚠️ image preview failed: {e}")
    return None

def preview_image_from_pdf(pdf_file):
    try:
        path = pdf_file
        if hasattr(pdf_file, 'name'):
            path = pdf_file.name
        if not path:
            return None
        p = Path(path)
        logs = []
        img = _pdf_to_image_first_page(p, p.parent, logs)
        return str(img) if img and img.exists() else None
    except Exception:
        return None

def _compile_tex_to_pdf(tex_path: Path, logs):
    """Generic TeX compile helper for a .tex file. Returns Path to PDF or None."""
    try:
        proj_dir = tex_path.parent
        import shutil as _sh, subprocess as _sp
        def _has(bin_name):
            return _sh.which(bin_name) is not None
        # Most-tolerant: latexmk first with pretex demoting errors; fallbacks inject pretex, too
        pretex = r"\nonstopmode\scrollmode\makeatletter\let\pgf@error\pgf@warning\let\GenericError\GenericWarning\let\PackageError\PackageWarning\makeatother"
        if _has("latexmk"):
            cmd = [
                "latexmk", "-pdf", "-pdflatex=xelatex", "-f",
                "-interaction=nonstopmode", "-file-line-error",
                f"-pretex={pretex}",
                tex_path.name,
            ]
            logs.append("▶ Compiling with latexmk (-pdf -pdflatex=xelatex -f, pretex demote errors) …")
        elif _has("xelatex"):
            injected = pretex + f"\\input{{{tex_path.name}}}"
            cmd = ["xelatex", "-interaction=nonstopmode", "-file-line-error", injected]
            logs.append("▶ Compiling with xelatex (pretex injected) …")
        elif _has("lualatex"):
            injected = pretex + f"\\input{{{tex_path.name}}}"
            cmd = ["lualatex", "-interaction=nonstopmode", "-file-line-error", injected]
            logs.append("▶ Compiling with lualatex (pretex injected) …")
        else:
            logs.append("⚠️ No TeX engine found (xelatex/lualatex/latexmk).")
            return None
        import os as _os
        _env = _os.environ.copy()
        texinputs = _env.get("TEXINPUTS", "")
        search = _os.pathsep.join([
            str(proj_dir), str(proj_dir) + "//",
            str(proj_dir.parent), str(proj_dir.parent) + "//",
        ])
        _env["TEXINPUTS"] = search + _os.pathsep + texinputs
        proc = _sp.run(cmd, cwd=str(proj_dir), stdout=_sp.PIPE, stderr=_sp.STDOUT, text=True, env=_env)
        if proc.stdout:
            logs.append(proc.stdout[-4000:])
        guess = proj_dir / (tex_path.stem + ".pdf")
        if proc.returncode != 0:
            # Be tolerant: if a PDF was produced despite errors, use it.
            if guess.exists():
                logs.append(f"⚠️ Compile returned code {proc.returncode}, but PDF exists; using it.")
                return guess
            logs.append(f"❌ PDF compile failed with code {proc.returncode} and no PDF produced.")
            return None
        return guess if guess.exists() else None
    except Exception as e:
        logs.append(f"⚠️ PDF compile error: {e}")
        return None

def _ensure_left_logo_or_disable(OUTPUT_DIR: Path, logs):
    """If no left_logo.* exists in logos/, comment out \logoleft line in poster_output.tex."""
    tex_path = OUTPUT_DIR / "poster_latex_proj" / "poster_output.tex"
    logos_dir = OUTPUT_DIR / "poster_latex_proj" / "logos"
    try:
        if not tex_path.exists():
            return False
        # any left_logo.* present?
        has_left = False
        if logos_dir.exists():
            for p in logos_dir.iterdir():
                if p.is_file() and p.stem == "left_logo":
                    has_left = True
                    break
        if has_left:
            return False
        txt = tex_path.read_text(encoding="utf-8")
        if "\\logoleft" in txt:
            new_txt = re.sub(r"^\\\s*logoleft\s*\{.*?\}\s*$", lambda m: "%" + m.group(0), txt, flags=re.MULTILINE)
            if new_txt != txt:
                tex_path.write_text(new_txt, encoding="utf-8")
                logs.append("ℹ️ No left_logo found; disabled \\\logoleft in poster_output.tex.")
                return True
    except Exception as e:
        logs.append(f"⚠️ Failed left_logo fallback: {e}")
    return False

def debug_compile():
    # Disabled minimal LaTeX debug; use the two pipeline-zip tests instead.
    return "<div style='color:#555'>Minimal debug disabled. Use 'Test repo output.zip' or 'Test last pipeline zip'.</div>"

def debug_compile_output_zip():
    """Compile the repo-root output.zip (a real LaTeX project) and return preview HTML + PDF path."""
    # Stage repo output.zip to runs/<id>/output.zip to follow pipeline layout, then delegate
    zip_path = ROOT / "output.zip"
    if not zip_path.exists():
        return (
            "<div style='color:#b00'><b>output.zip not found at repo root.</b></div>"
            + f"<div>Expected at: {zip_path}</div>",
            None,
        )
    logs = [f"🐞 Stage(repo zip) at {_now_str()}"]
    _, WORK_DIR, LOG_PATH, ZIP_PATH = _prepare_workspace(logs)
    try:
        shutil.copy2(zip_path, ZIP_PATH)
        logs.append(f"📦 Staged repo output.zip → runs/{WORK_DIR.name}/output.zip")
        _write_logs(LOG_PATH, logs)
    except Exception as e:
        logs.append(f"❌ Failed staging output.zip: {e}")
        _write_logs(LOG_PATH, logs)
        return "<div style='color:#b00'>Failed to stage output.zip</div>"
    return debug_compile_last_pipeline_zip()
    logs = [f"🐞 Debug(real) at {_now_str()}"]
    zip_path = ROOT / "output.zip"
    if not zip_path.exists():
        return (
            "<div style='color:#b00'><b>output.zip not found at repo root.</b></div>"
            + f"<div>Expected at: {zip_path}</div>"
        )

    # Prepare workspace
    run_id, WORK_DIR, LOG_PATH, _ = _prepare_workspace(logs)
    work_zip_dir = WORK_DIR / "zip_proj"
    work_zip_dir.mkdir(parents=True, exist_ok=True)
    logs.append(f"Workspace: runs/{WORK_DIR.name}")
    logs.append("Unzipping output.zip → zip_proj/")

    # Extract zip
    try:
        import zipfile as _zf
        with _zf.ZipFile(zip_path, 'r') as zf:
            zf.extractall(work_zip_dir)
    except Exception as e:
        logs.append(f"❌ unzip failed: {e}")
        _write_logs(LOG_PATH, logs)
        return "<div style='color:#b00'>Unzip failed.</div>", None

    # Locate poster_output.tex (fallback to poster.tex)
    tex_path = None
    for name in ("poster_output.tex", "poster.tex"):
        cand = list(work_zip_dir.rglob(name))
        if cand:
            tex_path = cand[0]
            break
    if tex_path is None:
        # fallback: any .tex
        cand = list(work_zip_dir.rglob("*.tex"))
        if cand:
            tex_path = cand[0]
    if tex_path is None:
        logs.append("❌ No .tex file found in output.zip")
        _write_logs(LOG_PATH, logs)
        return "<div style='color:#b00'>No .tex found in output.zip</div>", None

    # If left_logo missing, disable \logoleft
    try:
        logos_dir = tex_path.parent / "logos"
        has_left = False
        if logos_dir.exists():
            for p in logos_dir.iterdir():
                if p.is_file() and p.stem == "left_logo":
                    has_left = True
                    break
        if not has_left:
            txt = tex_path.read_text(encoding="utf-8")
            if "\\logoleft" in txt:
                import re as _re
                new_txt = _re.sub(r"^\\\s*logoleft\s*\{.*?\}\s*$", lambda m: "%" + m.group(0), txt, flags=_re.MULTILINE)
                if new_txt != txt:
                    tex_path.write_text(new_txt, encoding="utf-8")
                    logs.append("ℹ️ No left_logo found; disabled \\logoleft in zip project.")
    except Exception as e:
        logs.append(f"⚠️ left_logo adjust failed: {e}")

    # Ensure local fonts present in project and override theme to use them
    try:
        src_fonts = ROOT / "template" / "fonts"
        dst_fonts = work_zip_dir / "fonts"
        if src_fonts.exists():
            for root_dir, dirs, files in os.walk(src_fonts):
                rel = Path(root_dir).relative_to(src_fonts)
                out_dir = dst_fonts / rel
                out_dir.mkdir(parents=True, exist_ok=True)
                for fn in files:
                    if fn.lower().endswith((".ttf", ".otf")):
                        shutil.copy2(Path(root_dir)/fn, out_dir/fn)
            logs.append("📁 Copied local fonts → zip_proj/fonts/")
        # Copy repository theme .sty files into project root so they take precedence
        try:
            tmpl_dir = ROOT / "template"
            for sty in tmpl_dir.glob("*.sty"):
                shutil.copy2(sty, work_zip_dir / sty.name)
            logs.append("📄 Copied template/*.sty → zip_proj/")
        except Exception as e:
            logs.append(f"⚠️ Copy sty failed: {e}")
        # Copy repository theme .sty files into both root and the .tex dir so they take precedence
        try:
            tmpl_dir = ROOT / "template"
            for sty in tmpl_dir.glob("*.sty"):
                shutil.copy2(sty, work_zip_dir / sty.name)
                shutil.copy2(sty, tex_path.parent / sty.name)
            logs.append("📄 Copied template/*.sty → zip_proj/ and tex dir")
        except Exception as e:
            logs.append(f"⚠️ Copy sty failed: {e}")
        # Append overrides into theme file(s)
        for sty in work_zip_dir.rglob("beamerthemegemini.sty"):
            with open(sty, "a", encoding="utf-8") as fh:
                fh.write("\n% === overrides inserted for local fonts ===\n")
                fh.write("\\makeatletter\\@ifpackageloaded{fontspec}{%\n")
                fh.write("\\IfFileExists{fonts/Raleway/Raleway-Regular.ttf}{\\renewfontfamily\\Raleway[Path=fonts/Raleway/, UprightFont=*-Regular, ItalicFont=*-Italic, BoldFont=*-Bold, BoldItalicFont=*-BoldItalic, Ligatures=TeX]{Raleway}}{}\n")
                fh.write("\\IfFileExists{fonts/Lato/Lato-Regular.ttf}{\\renewfontfamily\\Lato[Path=fonts/Lato/, UprightFont=*-Light, ItalicFont=*-LightItalic, BoldFont=*-Regular, BoldItalicFont=*-Italic, Ligatures=TeX]{Lato}\\setsansfont{Lato}[Path=fonts/Lato/, UprightFont=*-Light, ItalicFont=*-LightItalic, BoldFont=*-Regular, BoldItalicFont=*-Italic]}{}\n")
                fh.write("}{ }\\makeatother\n")
            logs.append(f"🛠️ Appended local font overrides in {sty.relative_to(work_zip_dir)}")
    except Exception as e:
        logs.append(f"⚠️ Local font setup failed: {e}")

    # Compile to PDF
    pdf_path = _compile_tex_to_pdf(tex_path, logs)
    if not pdf_path or not pdf_path.exists():
        logs.append("❌ Failed to compile zip PDF.")
        _write_logs(LOG_PATH, logs)
        return (
            "<div style='color:#b00'><b>Compile failed.</b></div>"
            + "<pre style='white-space:pre-wrap;background:#f7f7f8;padding:8px;border-radius:6px'>"
            + "\n".join(logs)
            + "</pre>",
            None,
        )

    try:
        # Use served file path to avoid data: URI issues
        html = _pdf_preview_html(pdf_path, height="700px")
        _write_logs(LOG_PATH, logs)
        return html, str(pdf_path)
    except Exception as e:
        logs.append(f"⚠️ preview failed: {e}")
        _write_logs(LOG_PATH, logs)
        return f"<div>Compiled but preview failed: {e}</div>", None

def _find_last_pipeline_zip():
    try:
        candidates = []
        for d in RUNS_DIR.iterdir():
            try:
                if d.is_dir():
                    z = d / "output.zip"
                    if z.exists():
                        candidates.append((z.stat().st_mtime, z))
            except Exception:
                pass
        if not candidates:
            return None
        candidates.sort(key=lambda x: x[0], reverse=True)
        return candidates[0][1]
    except Exception:
        return None

def debug_compile_last_pipeline_zip():
    """Find the most recent runs/*/output.zip from pipeline, compile, and return preview HTML + PDF path."""
    logs = [f"🐞 Debug(last-pipeline-zip) at {_now_str()}"]
    last_zip = _find_last_pipeline_zip()
    if not last_zip:
        repo_zip = ROOT / "output.zip"
        if repo_zip.exists():
            try:
                _, W, L, Z = _prepare_workspace(logs)
                shutil.copy2(repo_zip, Z)
                logs.append(f"📦 Auto-staged repo output.zip → runs/{W.name}/output.zip")
                last_zip = Z
            except Exception as e:
                logs.append(f"❌ Auto-stage failed: {e}")
                return "<div style='color:#b00'>No recent pipeline output.zip found and auto-stage failed.</div>"
        else:
            return "<div style='color:#b00'>No recent pipeline output.zip found under runs/.</div>", None

    # Prepare workspace
    run_id, WORK_DIR, LOG_PATH, _ = _prepare_workspace(logs)
    work_zip_dir = WORK_DIR / "zip_last"
    work_zip_dir.mkdir(parents=True, exist_ok=True)
    logs.append(f"Workspace: runs/{WORK_DIR.name}")
    logs.append(f"Using: {last_zip}")

    # Extract zip
    try:
        import zipfile as _zf
        with _zf.ZipFile(last_zip, 'r') as zf:
            zf.extractall(work_zip_dir)
    except Exception as e:
        logs.append(f"❌ unzip failed: {e}")
        _write_logs(LOG_PATH, logs)
        return "<div style='color:#b00'>Unzip failed.</div>", None

    # Locate tex
    tex_path = None
    for name in ("poster_output.tex", "poster.tex"):
        cand = list(work_zip_dir.rglob(name))
        if cand:
            tex_path = cand[0]
            break
    if tex_path is None:
        cand = list(work_zip_dir.rglob("*.tex"))
        if cand:
            tex_path = cand[0]
    if tex_path is None:
        logs.append("❌ No .tex file found in last pipeline zip")
        _write_logs(LOG_PATH, logs)
        return "<div style='color:#b00'>No .tex found in last pipeline zip</div>", None

    # Ensure local fonts and theme precedence (same as other debug path)
    try:
        src_fonts = ROOT / "template" / "fonts"
        dst_fonts = work_zip_dir / "fonts"
        if src_fonts.exists():
            for root_dir, dirs, files in os.walk(src_fonts):
                rel = Path(root_dir).relative_to(src_fonts)
                out_dir = dst_fonts / rel
                out_dir.mkdir(parents=True, exist_ok=True)
                for fn in files:
                    if fn.lower().endswith((".ttf", ".otf")):
                        shutil.copy2(Path(root_dir)/fn, out_dir/fn)
            logs.append("📁 Copied local fonts → zip_last/fonts/")
        # Copy repository theme .sty next to tex and at root
        try:
            tmpl_dir = ROOT / "template"
            for sty in tmpl_dir.glob("*.sty"):
                shutil.copy2(sty, work_zip_dir / sty.name)
                shutil.copy2(sty, tex_path.parent / sty.name)
            logs.append("📄 Copied template/*.sty → zip_last/ and tex dir")
        except Exception as e:
            logs.append(f"⚠️ Copy sty failed: {e}")
    except Exception as e:
        logs.append(f"⚠️ Local font setup failed: {e}")

    # Compile to PDF
    pdf_path = _compile_tex_to_pdf(tex_path, logs)
    if not pdf_path or not pdf_path.exists():
        logs.append("❌ Failed to compile last pipeline zip PDF.")
        _write_logs(LOG_PATH, logs)
        return (
            "<div style='color:#b00'><b>Compile failed.</b></div>"
            + "<pre style='white-space:pre-wrap;background:#f7f7f8;padding:8px;border-radius:6px'>"
            + "\n".join(logs)
            + "</pre>",
            None,
        )
    try:
        _write_logs(LOG_PATH, logs)
        return "", str(pdf_path)
    except Exception as e:
        logs.append(f"⚠️ preview failed: {e}")
        _write_logs(LOG_PATH, logs)
        return f"<div>Compiled but preview failed: {e}</div>", None

def _find_last_pipeline_zip():
    try:
        candidates = []
        for d in RUNS_DIR.iterdir():
            try:
                if d.is_dir():
                    z = d / "output.zip"
                    if z.exists():
                        candidates.append((z.stat().st_mtime, z))
            except Exception:
                pass
        if not candidates:
            return None
        candidates.sort(key=lambda x: x[0], reverse=True)
        return candidates[0][1]
    except Exception:
        return None

def debug_compile_last_pipeline_zip():
    """Find the most recent runs/*/output.zip from pipeline, compile, and return preview HTML + PDF path."""
    logs = [f"🐞 Debug(last-pipeline-zip) at {_now_str()}"]
    last_zip = _find_last_pipeline_zip()
    if not last_zip:
        repo_zip = ROOT / "output.zip"
        if repo_zip.exists():
            try:
                _, W, L, Z = _prepare_workspace(logs)
                shutil.copy2(repo_zip, Z)
                logs.append(f"📦 Auto-staged repo output.zip → runs/{W.name}/output.zip")
                last_zip = Z
            except Exception as e:
                logs.append(f"❌ Auto-stage failed: {e}")
                return "<div style='color:#b00'>No recent pipeline output.zip found and auto-stage failed.</div>"
        else:
            return "<div style='color:#b00'>No recent pipeline output.zip found under runs/.</div>", None

    # Prepare workspace
    run_id, WORK_DIR, LOG_PATH, _ = _prepare_workspace(logs)
    work_zip_dir = WORK_DIR / "zip_last"
    work_zip_dir.mkdir(parents=True, exist_ok=True)
    logs.append(f"Workspace: runs/{WORK_DIR.name}")
    logs.append(f"Using: {last_zip}")

    # Extract zip
    try:
        import zipfile as _zf
        with _zf.ZipFile(last_zip, 'r') as zf:
            zf.extractall(work_zip_dir)
    except Exception as e:
        logs.append(f"❌ unzip failed: {e}")
        _write_logs(LOG_PATH, logs)
        return "<div style='color:#b00'>Unzip failed.</div>", None

    # Locate tex
    tex_path = None
    for name in ("poster_output.tex", "poster.tex"):
        cand = list(work_zip_dir.rglob(name))
        if cand:
            tex_path = cand[0]
            break
    if tex_path is None:
        cand = list(work_zip_dir.rglob("*.tex"))
        if cand:
            tex_path = cand[0]
    if tex_path is None:
        logs.append("❌ No .tex file found in last pipeline zip")
        _write_logs(LOG_PATH, logs)
        return "<div style='color:#b00'>No .tex found in last pipeline zip</div>", None

    # Ensure local fonts and theme precedence (same as other debug path)
    try:
        src_fonts = ROOT / "template" / "fonts"
        dst_fonts = work_zip_dir / "fonts"
        if src_fonts.exists():
            for root_dir, dirs, files in os.walk(src_fonts):
                rel = Path(root_dir).relative_to(src_fonts)
                out_dir = dst_fonts / rel
                out_dir.mkdir(parents=True, exist_ok=True)
                for fn in files:
                    if fn.lower().endswith((".ttf", ".otf")):
                        shutil.copy2(Path(root_dir)/fn, out_dir/fn)
            logs.append("📁 Copied local fonts → zip_last/fonts/")
        # Copy repository theme .sty next to tex and at root
        try:
            tmpl_dir = ROOT / "template"
            for sty in tmpl_dir.glob("*.sty"):
                shutil.copy2(sty, work_zip_dir / sty.name)
                shutil.copy2(sty, tex_path.parent / sty.name)
            logs.append("📄 Copied template/*.sty → zip_last/ and tex dir")
        except Exception as e:
            logs.append(f"⚠️ Copy sty failed: {e}")
    except Exception as e:
        logs.append(f"⚠️ Local font setup failed: {e}")

    # Compile to PDF
    pdf_path = _compile_tex_to_pdf(tex_path, logs)
    if not pdf_path or not pdf_path.exists():
        logs.append("❌ Failed to compile last pipeline zip PDF.")
        _write_logs(LOG_PATH, logs)
        return (
            "<div style='color:#b00'><b>Compile failed.</b></div>"
            + "<pre style='white-space:pre-wrap;background:#f7f7f8;padding:8px;border-radius:6px'>"
            + "\n".join(logs)
            + "</pre>",
            None,
        )
    try:
        b64 = base64.b64encode(pdf_path.read_bytes()).decode("utf-8")
        open_tab = f"<a target='_blank' rel='noopener' href='data:application/pdf;base64,{b64}'>Open PDF in new tab</a>"
        html = (
            f"<div style='margin-bottom:8px'>{open_tab}</div>"
            + _pdf_to_iframe_html(pdf_path, height="700px")
        )
        _write_logs(LOG_PATH, logs)
        return "", str(pdf_path)
    except Exception as e:
        logs.append(f"⚠️ preview failed: {e}")
        _write_logs(LOG_PATH, logs)
        return f"<div>Compiled but preview failed: {e}</div>", None

def debug_compile_uploaded_zip(zip_file):
    """Compile an uploaded poster zip (user-provided); return preview HTML + PDF path."""
    logs = [f"🐞 Debug(upload) at {_now_str()}"]
    if not zip_file:
        return "<div style='color:#b00'>Please upload a .zip file first.</div>", None
    # Prepare workspace
    run_id, WORK_DIR, LOG_PATH, _ = _prepare_workspace(logs)
    work_zip_dir = WORK_DIR / "zip_upload"
    work_zip_dir.mkdir(parents=True, exist_ok=True)
    # Save uploaded zip
    up_path = work_zip_dir / "input.zip"
    try:
        shutil.copy(zip_file.name, up_path)
    except Exception as e:
        logs.append(f"❌ save upload failed: {e}")
        _write_logs(LOG_PATH, logs)
        return "<div style='color:#b00'>Save upload failed.</div>", None
    # Extract
    try:
        import zipfile as _zf
        with _zf.ZipFile(up_path, 'r') as zf:
            zf.extractall(work_zip_dir)
    except Exception as e:
        logs.append(f"❌ unzip failed: {e}")
        _write_logs(LOG_PATH, logs)
        return "<div style='color:#b00'>Unzip failed.</div>", None
    # Find tex
    tex_path = None
    for name in ("poster_output.tex", "poster.tex"):
        cand = list(work_zip_dir.rglob(name))
        if cand:
            tex_path = cand[0]
            break
    if tex_path is None:
        cand = list(work_zip_dir.rglob("*.tex"))
        if cand:
            tex_path = cand[0]
    if tex_path is None:
        logs.append("❌ No .tex file found in uploaded zip")
        _write_logs(LOG_PATH, logs)
        return "<div style='color:#b00'>No .tex found in uploaded zip</div>", None
    # Disable logoleft if missing; also ensure local fonts and override theme to use them
    try:
        logos_dir = tex_path.parent / "logos"
        has_left = False
        if logos_dir.exists():
            for p in logos_dir.iterdir():
                if p.is_file() and p.stem == "left_logo":
                    has_left = True
                    break
        if not has_left:
            txt = tex_path.read_text(encoding="utf-8")
            if "\\logoleft" in txt:
                import re as _re
                new_txt = _re.sub(r"^\\\s*logoleft\s*\{.*?\}\s*$", lambda m: "%" + m.group(0), txt, flags=_re.MULTILINE)
                if new_txt != txt:
                    tex_path.write_text(new_txt, encoding="utf-8")
                    logs.append("ℹ️ No left_logo found; disabled \\logoleft in uploaded project.")
        # Copy repo-local fonts into the zip project under ./fonts/, then append overrides into theme
        try:
            src_fonts = ROOT / "template" / "fonts"
            dst_fonts = work_zip_dir / "fonts"
            if src_fonts.exists():
                for root_dir, dirs, files in os.walk(src_fonts):
                    rel = Path(root_dir).relative_to(src_fonts)
                    out_dir = dst_fonts / rel
                    out_dir.mkdir(parents=True, exist_ok=True)
                    for fn in files:
                        if fn.lower().endswith((".ttf", ".otf")):
                            shutil.copy2(Path(root_dir)/fn, out_dir/fn)
                logs.append("📁 Copied local fonts → zip_upload/fonts/")
            for sty in work_zip_dir.rglob("beamerthemegemini.sty"):
                with open(sty, "a", encoding="utf-8") as fh:
                    fh.write("\n% === overrides inserted for local fonts ===\n")
                    fh.write("\\makeatletter\\@ifpackageloaded{fontspec}{%\n")
                    fh.write("\\IfFileExists{fonts/Raleway/Raleway-Regular.ttf}{\\renewfontfamily\\Raleway[Path=fonts/Raleway/, UprightFont=*-Regular, ItalicFont=*-Italic, BoldFont=*-Bold, BoldItalicFont=*-BoldItalic, Ligatures=TeX]{Raleway}}{}\n")
                    fh.write("\\IfFileExists{fonts/Lato/Lato-Regular.ttf}{\\renewfontfamily\\Lato[Path=fonts/Lato/, UprightFont=*-Light, ItalicFont=*-LightItalic, BoldFont=*-Regular, BoldItalicFont=*-Italic, Ligatures=TeX]{Lato}\\setsansfont{Lato}[Path=fonts/Lato/, UprightFont=*-Light, ItalicFont=*-LightItalic, BoldFont=*-Regular, BoldItalicFont=*-Italic]}{}\n")
                    fh.write("}{ }\\makeatother\n")
                logs.append(f"🛠️ Appended local font overrides in {sty.relative_to(work_zip_dir)}")
        except Exception as e:
            logs.append(f"⚠️ Local font setup failed: {e}")
    except Exception as e:
        logs.append(f"⚠️ left_logo adjust failed: {e}")
    # Compile
    pdf_path = _compile_tex_to_pdf(tex_path, logs)
    if not pdf_path or not pdf_path.exists():
        logs.append("❌ Failed to compile uploaded zip PDF.")
        _write_logs(LOG_PATH, logs)
        return (
            "<div style='color:#b00'><b>Compile failed.</b></div>"
            + "<pre style='white-space:pre-wrap;background:#f7f7f8;padding:8px;border-radius:6px'>"
            + "\n".join(logs)
            + "</pre>",
            None,
        )
    try:
        _write_logs(LOG_PATH, logs)
        return "", str(pdf_path)
    except Exception as e:
        logs.append(f"⚠️ preview failed: {e}")
        _write_logs(LOG_PATH, logs)
        return f"<div>Compiled but preview failed: {e}</div>", None

def debug_compile_output_zip():
    """Compile the repo-root output.zip (a real LaTeX project) and preview the resulting PDF."""
    # Stage repo output.zip to runs/<id>/output.zip to follow pipeline layout, then delegate
    zip_path = ROOT / "output.zip"
    if not zip_path.exists():
        return (
            "<div style='color:#b00'><b>output.zip not found at repo root.</b></div>"
            + f"<div>Expected at: {zip_path}</div>",
            None,
        )
    logs = [f"🐞 Stage(repo zip) at {_now_str()}"]
    _, WORK_DIR, LOG_PATH, ZIP_PATH = _prepare_workspace(logs)
    try:
        shutil.copy2(zip_path, ZIP_PATH)
        logs.append(f"📦 Staged repo output.zip → runs/{WORK_DIR.name}/output.zip")
        _write_logs(LOG_PATH, logs)
    except Exception as e:
        logs.append(f"❌ Failed staging output.zip: {e}")
        _write_logs(LOG_PATH, logs)
        return "<div style='color:#b00'>Failed to stage output.zip</div>"
    return debug_compile_last_pipeline_zip()
    logs = [f"🐞 Debug(real) at {_now_str()}"]
    zip_path = ROOT / "output.zip"
    if not zip_path.exists():
        return (
            "<div style='color:#b00'><b>output.zip not found at repo root.</b></div>"
            + f"<div>Expected at: {zip_path}</div>"
        )

    # Prepare workspace
    run_id, WORK_DIR, LOG_PATH, _ = _prepare_workspace(logs)
    work_zip_dir = WORK_DIR / "zip_proj"
    work_zip_dir.mkdir(parents=True, exist_ok=True)
    logs.append(f"Workspace: runs/{WORK_DIR.name}")
    logs.append("Unzipping output.zip → zip_proj/")

    # Extract zip
    try:
        import zipfile as _zf
        with _zf.ZipFile(zip_path, 'r') as zf:
            zf.extractall(work_zip_dir)
    except Exception as e:
        logs.append(f"❌ unzip failed: {e}")
        _write_logs(LOG_PATH, logs)
        return "<div style='color:#b00'>Unzip failed.</div>", None

    # Locate poster_output.tex (fallback to poster.tex)
    tex_path = None
    for name in ("poster_output.tex", "poster.tex"):
        cand = list(work_zip_dir.rglob(name))
        if cand:
            tex_path = cand[0]
            break
    if tex_path is None:
        # fallback: any .tex
        cand = list(work_zip_dir.rglob("*.tex"))
        if cand:
            tex_path = cand[0]
    if tex_path is None:
        logs.append("❌ No .tex file found in output.zip")
        _write_logs(LOG_PATH, logs)
        return "<div style='color:#b00'>No .tex found in output.zip</div>", None

    # If left_logo missing, disable \logoleft
    try:
        logos_dir = tex_path.parent / "logos"
        has_left = False
        if logos_dir.exists():
            for p in logos_dir.iterdir():
                if p.is_file() and p.stem == "left_logo":
                    has_left = True
                    break
        if not has_left:
            txt = tex_path.read_text(encoding="utf-8")
            if "\\logoleft" in txt:
                import re as _re
                new_txt = _re.sub(r"^\\\s*logoleft\s*\{.*?\}\s*$", lambda m: "%" + m.group(0), txt, flags=_re.MULTILINE)
                if new_txt != txt:
                    tex_path.write_text(new_txt, encoding="utf-8")
                    logs.append("ℹ️ No left_logo found; disabled \\logoleft in zip project.")
    except Exception as e:
        logs.append(f"⚠️ left_logo adjust failed: {e}")

    # Compile to PDF
    pdf_path = _compile_tex_to_pdf(tex_path, logs)
    if not pdf_path or not pdf_path.exists():
        logs.append("❌ Failed to compile zip PDF.")
        _write_logs(LOG_PATH, logs)
        return (
            "<div style='color:#b00'><b>Compile failed.</b></div>"
            + "<pre style='white-space:pre-wrap;background:#f7f7f8;padding:8px;border-radius:6px'>"
            + "\n".join(logs)
            + "</pre>",
            None,
        )

    try:
        b64 = base64.b64encode(pdf_path.read_bytes()).decode("utf-8")
        open_tab = f"<a target='_blank' rel='noopener' href='data:application/pdf;base64,{b64}'>Open PDF in new tab</a>"
        html = (
            f"<div style='margin-bottom:8px'>{open_tab}</div>"
            + _pdf_to_iframe_html(pdf_path, height="700px")
        )
        _write_logs(LOG_PATH, logs)
        return "", str(pdf_path)
    except Exception as e:
        logs.append(f"⚠️ preview failed: {e}")
        _write_logs(LOG_PATH, logs)
        return f"<div>Compiled but preview failed: {e}</div>", None

def _find_last_pipeline_zip():
    try:
        candidates = []
        for d in RUNS_DIR.iterdir():
            try:
                if d.is_dir():
                    z = d / "output.zip"
                    if z.exists():
                        candidates.append((z.stat().st_mtime, z))
            except Exception:
                pass
        if not candidates:
            return None
        candidates.sort(key=lambda x: x[0], reverse=True)
        return candidates[0][1]
    except Exception:
        return None

def debug_compile_last_pipeline_zip():
    """Find the most recent runs/*/output.zip from pipeline, compile, and return preview HTML + PDF path."""
    logs = [f"🐞 Debug(last-pipeline-zip) at {_now_str()}"]
    last_zip = _find_last_pipeline_zip()
    if not last_zip:
        repo_zip = ROOT / "output.zip"
        if repo_zip.exists():
            try:
                _, W, L, Z = _prepare_workspace(logs)
                shutil.copy2(repo_zip, Z)
                logs.append(f"📦 Auto-staged repo output.zip → runs/{W.name}/output.zip")
                last_zip = Z
            except Exception as e:
                logs.append(f"❌ Auto-stage failed: {e}")
                return "<div style='color:#b00'>No recent pipeline output.zip found and auto-stage failed.</div>"
        else:
            return "<div style='color:#b00'>No recent pipeline output.zip found under runs/.</div>", None

    # Prepare workspace
    run_id, WORK_DIR, LOG_PATH, _ = _prepare_workspace(logs)
    work_zip_dir = WORK_DIR / "zip_last"
    work_zip_dir.mkdir(parents=True, exist_ok=True)
    logs.append(f"Workspace: runs/{WORK_DIR.name}")
    logs.append(f"Using: {last_zip}")

    # Extract zip
    try:
        import zipfile as _zf
        with _zf.ZipFile(last_zip, 'r') as zf:
            zf.extractall(work_zip_dir)
    except Exception as e:
        logs.append(f"❌ unzip failed: {e}")
        _write_logs(LOG_PATH, logs)
        return "<div style='color:#b00'>Unzip failed.</div>", None

    # Locate tex
    tex_path = None
    for name in ("poster_output.tex", "poster.tex"):
        cand = list(work_zip_dir.rglob(name))
        if cand:
            tex_path = cand[0]
            break
    if tex_path is None:
        cand = list(work_zip_dir.rglob("*.tex"))
        if cand:
            tex_path = cand[0]
    if tex_path is None:
        logs.append("❌ No .tex file found in last pipeline zip")
        _write_logs(LOG_PATH, logs)
        return "<div style='color:#b00'>No .tex found in last pipeline zip</div>", None

    # Ensure local fonts and theme precedence (same as other debug path)
    try:
        src_fonts = ROOT / "template" / "fonts"
        dst_fonts = work_zip_dir / "fonts"
        if src_fonts.exists():
            for root_dir, dirs, files in os.walk(src_fonts):
                rel = Path(root_dir).relative_to(src_fonts)
                out_dir = dst_fonts / rel
                out_dir.mkdir(parents=True, exist_ok=True)
                for fn in files:
                    if fn.lower().endswith((".ttf", ".otf")):
                        shutil.copy2(Path(root_dir)/fn, out_dir/fn)
            logs.append("📁 Copied local fonts → zip_last/fonts/")
        # Copy repository theme .sty next to tex and at root
        try:
            tmpl_dir = ROOT / "template"
            for sty in tmpl_dir.glob("*.sty"):
                shutil.copy2(sty, work_zip_dir / sty.name)
                shutil.copy2(sty, tex_path.parent / sty.name)
            logs.append("📄 Copied template/*.sty → zip_last/ and tex dir")
        except Exception as e:
            logs.append(f"⚠️ Copy sty failed: {e}")
    except Exception as e:
        logs.append(f"⚠️ Local font setup failed: {e}")

    # Compile to PDF
    pdf_path = _compile_tex_to_pdf(tex_path, logs)
    if not pdf_path or not pdf_path.exists():
        logs.append("❌ Failed to compile last pipeline zip PDF.")
        _write_logs(LOG_PATH, logs)
        return (
            "<div style='color:#b00'><b>Compile failed.</b></div>"
            + "<pre style='white-space:pre-wrap;background:#f7f7f8;padding:8px;border-radius:6px'>"
            + "\n".join(logs)
            + "</pre>",
            None,
        )
    try:
        b64 = base64.b64encode(pdf_path.read_bytes()).decode("utf-8")
        open_tab = f"<a target='_blank' rel='noopener' href='data:application/pdf;base64,{b64}'>Open PDF in new tab</a>"
        html = (
            f"<div style='margin-bottom:8px'>{open_tab}</div>"
            + _pdf_to_iframe_html(pdf_path, height="700px")
        )
        _write_logs(LOG_PATH, logs)
        return "", str(pdf_path)
    except Exception as e:
        logs.append(f"⚠️ preview failed: {e}")
        _write_logs(LOG_PATH, logs)
        return f"<div>Compiled but preview failed: {e}</div>", None

def debug_compile_uploaded_zip(zip_file):
    """Compile an uploaded poster zip (user-provided); return preview HTML + PDF path."""
    logs = [f"🐞 Debug(upload) at {_now_str()}"]
    if not zip_file:
        return "<div style='color:#b00'>Please upload a .zip file first.</div>", None
    # Prepare workspace
    run_id, WORK_DIR, LOG_PATH, _ = _prepare_workspace(logs)
    work_zip_dir = WORK_DIR / "zip_upload"
    work_zip_dir.mkdir(parents=True, exist_ok=True)
    # Save uploaded zip
    up_path = work_zip_dir / "input.zip"
    try:
        shutil.copy(zip_file.name, up_path)
    except Exception as e:
        logs.append(f"❌ save upload failed: {e}")
        _write_logs(LOG_PATH, logs)
        return "<div style='color:#b00'>Save upload failed.</div>", None
    # Extract
    try:
        import zipfile as _zf
        with _zf.ZipFile(up_path, 'r') as zf:
            zf.extractall(work_zip_dir)
    except Exception as e:
        logs.append(f"❌ unzip failed: {e}")
        _write_logs(LOG_PATH, logs)
        return "<div style='color:#b00'>Unzip failed.</div>", None
    # Find tex
    tex_path = None
    for name in ("poster_output.tex", "poster.tex"):
        cand = list(work_zip_dir.rglob(name))
        if cand:
            tex_path = cand[0]
            break
    if tex_path is None:
        cand = list(work_zip_dir.rglob("*.tex"))
        if cand:
            tex_path = cand[0]
    if tex_path is None:
        logs.append("❌ No .tex file found in uploaded zip")
        _write_logs(LOG_PATH, logs)
        return "<div style='color:#b00'>No .tex found in uploaded zip</div>"
    # Disable logoleft if missing
    try:
        logos_dir = tex_path.parent / "logos"
        has_left = False
        if logos_dir.exists():
            for p in logos_dir.iterdir():
                if p.is_file() and p.stem == "left_logo":
                    has_left = True
                    break
        if not has_left:
            txt = tex_path.read_text(encoding="utf-8")
            if "\\logoleft" in txt:
                import re as _re
                new_txt = _re.sub(r"^\\\s*logoleft\s*\{.*?\}\s*$", lambda m: "%" + m.group(0), txt, flags=_re.MULTILINE)
                if new_txt != txt:
                    tex_path.write_text(new_txt, encoding="utf-8")
                    logs.append("ℹ️ No left_logo found; disabled \\logoleft in uploaded project.")
    except Exception as e:
        logs.append(f"⚠️ left_logo adjust failed: {e}")
    # Compile
    pdf_path = _compile_tex_to_pdf(tex_path, logs)
    if not pdf_path or not pdf_path.exists():
        logs.append("❌ Failed to compile uploaded zip PDF.")
        _write_logs(LOG_PATH, logs)
        return (
            "<div style='color:#b00'><b>Compile failed.</b></div>"
            + "<pre style='white-space:pre-wrap;background:#f7f7f8;padding:8px;border-radius:6px'>"
            + "\n".join(logs)
            + "</pre>",
            None,
        )
    try:
        b64 = base64.b64encode(pdf_path.read_bytes()).decode("utf-8")
        open_tab = f"<a target='_blank' rel='noopener' href='data:application/pdf;base64,{b64}'>Open PDF in new tab</a>"
        html = (
            f"<div style='margin-bottom:8px'>{open_tab}</div>"
            + _pdf_to_iframe_html(pdf_path, height="700px")
        )
        _write_logs(LOG_PATH, logs)
        return html, str(pdf_path)
    except Exception as e:
        logs.append(f"⚠️ preview failed: {e}")
        _write_logs(LOG_PATH, logs)
        return f"<div>Compiled but preview failed: {e}</div>", None

def debug_compile_output_zip():
    """Compile the repo-root output.zip (a real LaTeX project) and preview the resulting PDF."""
    # Stage repo output.zip to runs/<id>/output.zip to follow pipeline layout, then delegate
    zip_path = ROOT / "output.zip"
    if not zip_path.exists():
        return (
            "<div style='color:#b00'><b>output.zip not found at repo root.</b></div>"
            + f"<div>Expected at: {zip_path}</div>",
            None,
        )
    logs = [f"🐞 Stage(repo zip) at {_now_str()}"]
    _, WORK_DIR, LOG_PATH, ZIP_PATH = _prepare_workspace(logs)
    try:
        shutil.copy2(zip_path, ZIP_PATH)
        logs.append(f"📦 Staged repo output.zip → runs/{WORK_DIR.name}/output.zip")
        _write_logs(LOG_PATH, logs)
    except Exception as e:
        logs.append(f"❌ Failed staging output.zip: {e}")
        _write_logs(LOG_PATH, logs)
        return "<div style='color:#b00'>Failed to stage output.zip</div>"
    return debug_compile_last_pipeline_zip()
    logs = [f"🐞 Debug(real) at {_now_str()}"]
    zip_path = ROOT / "output.zip"
    if not zip_path.exists():
        return (
            "<div style='color:#b00'><b>output.zip not found at repo root.</b></div>"
            + f"<div>Expected at: {zip_path}</div>"
        )

    # Prepare workspace
    run_id, WORK_DIR, LOG_PATH, _ = _prepare_workspace(logs)
    work_zip_dir = WORK_DIR / "zip_proj"
    work_zip_dir.mkdir(parents=True, exist_ok=True)
    logs.append(f"Workspace: runs/{WORK_DIR.name}")
    logs.append("Unzipping output.zip → zip_proj/")

    # Extract zip
    try:
        import zipfile as _zf
        with _zf.ZipFile(zip_path, 'r') as zf:
            zf.extractall(work_zip_dir)
    except Exception as e:
        logs.append(f"❌ unzip failed: {e}")
        _write_logs(LOG_PATH, logs)
        return "<div style='color:#b00'>Unzip failed.</div>", None

    # Locate poster_output.tex (fallback to poster.tex)
    tex_path = None
    for name in ("poster_output.tex", "poster.tex"):
        cand = list(work_zip_dir.rglob(name))
        if cand:
            tex_path = cand[0]
            break
    if tex_path is None:
        # fallback: any .tex
        cand = list(work_zip_dir.rglob("*.tex"))
        if cand:
            tex_path = cand[0]
    if tex_path is None:
        logs.append("❌ No .tex file found in output.zip")
        _write_logs(LOG_PATH, logs)
        return "<div style='color:#b00'>No .tex found in output.zip</div>", None

    # If left_logo missing, disable \logoleft
    try:
        logos_dir = tex_path.parent / "logos"
        has_left = False
        if logos_dir.exists():
            for p in logos_dir.iterdir():
                if p.is_file() and p.stem == "left_logo":
                    has_left = True
                    break
        if not has_left:
            txt = tex_path.read_text(encoding="utf-8")
            if "\\logoleft" in txt:
                import re as _re
                new_txt = _re.sub(r"^\\\s*logoleft\s*\{.*?\}\s*$", lambda m: "%" + m.group(0), txt, flags=_re.MULTILINE)
                if new_txt != txt:
                    tex_path.write_text(new_txt, encoding="utf-8")
                    logs.append("ℹ️ No left_logo found; disabled \\logoleft in zip project.")
    except Exception as e:
        logs.append(f"⚠️ left_logo adjust failed: {e}")

    # Compile to PDF
    pdf_path = _compile_tex_to_pdf(tex_path, logs)
    if not pdf_path or not pdf_path.exists():
        logs.append("❌ Failed to compile zip PDF.")
        _write_logs(LOG_PATH, logs)
        return (
            "<div style='color:#b00'><b>Compile failed.</b></div>"
            + "<pre style='white-space:pre-wrap;background:#f7f7f8;padding:8px;border-radius:6px'>"
            + "\n".join(logs)
            + "</pre>",
            None,
        )

    try:
        b64 = base64.b64encode(pdf_path.read_bytes()).decode("utf-8")
        open_tab = f"<a target='_blank' rel='noopener' href='data:application/pdf;base64,{b64}'>Open PDF in new tab</a>"
        html = (
            f"<div style='margin-bottom:8px'>{open_tab}</div>"
            + _pdf_to_iframe_html(pdf_path, height="700px")
        )
        _write_logs(LOG_PATH, logs)
        return html, str(pdf_path)
    except Exception as e:
        logs.append(f"⚠️ preview failed: {e}")
        _write_logs(LOG_PATH, logs)
        return f"<div>Compiled but preview failed: {e}</div>", None

def _find_last_pipeline_zip():
    try:
        candidates = []
        for d in RUNS_DIR.iterdir():
            try:
                if d.is_dir():
                    z = d / "output.zip"
                    if z.exists():
                        candidates.append((z.stat().st_mtime, z))
            except Exception:
                pass
        if not candidates:
            return None
        candidates.sort(key=lambda x: x[0], reverse=True)
        return candidates[0][1]
    except Exception:
        return None

def debug_compile_last_pipeline_zip():
    """Find the most recent runs/*/output.zip from pipeline, compile, and return preview HTML + PDF path."""
    logs = [f"🐞 Debug(last-pipeline-zip) at {_now_str()}"]
    last_zip = _find_last_pipeline_zip()
    if not last_zip:
        repo_zip = ROOT / "output.zip"
        if repo_zip.exists():
            try:
                _, W, L, Z = _prepare_workspace(logs)
                shutil.copy2(repo_zip, Z)
                logs.append(f"📦 Auto-staged repo output.zip → runs/{W.name}/output.zip")
                last_zip = Z
            except Exception as e:
                logs.append(f"❌ Auto-stage failed: {e}")
                return "<div style='color:#b00'>No recent pipeline output.zip found and auto-stage failed.</div>"
        else:
            return "<div style='color:#b00'>No recent pipeline output.zip found under runs/.</div>", None

    # Prepare workspace
    run_id, WORK_DIR, LOG_PATH, _ = _prepare_workspace(logs)
    work_zip_dir = WORK_DIR / "zip_last"
    work_zip_dir.mkdir(parents=True, exist_ok=True)
    logs.append(f"Workspace: runs/{WORK_DIR.name}")
    logs.append(f"Using: {last_zip}")

    # Extract zip
    try:
        import zipfile as _zf
        with _zf.ZipFile(last_zip, 'r') as zf:
            zf.extractall(work_zip_dir)
    except Exception as e:
        logs.append(f"❌ unzip failed: {e}")
        _write_logs(LOG_PATH, logs)
        return "<div style='color:#b00'>Unzip failed.</div>", None

    # Locate tex
    tex_path = None
    for name in ("poster_output.tex", "poster.tex"):
        cand = list(work_zip_dir.rglob(name))
        if cand:
            tex_path = cand[0]
            break
    if tex_path is None:
        cand = list(work_zip_dir.rglob("*.tex"))
        if cand:
            tex_path = cand[0]
    if tex_path is None:
        logs.append("❌ No .tex file found in last pipeline zip")
        _write_logs(LOG_PATH, logs)
        return "<div style='color:#b00'>No .tex found in last pipeline zip</div>", None

    # Ensure local fonts and theme precedence (same as other debug path)
    try:
        src_fonts = ROOT / "template" / "fonts"
        dst_fonts = work_zip_dir / "fonts"
        if src_fonts.exists():
            for root_dir, dirs, files in os.walk(src_fonts):
                rel = Path(root_dir).relative_to(src_fonts)
                out_dir = dst_fonts / rel
                out_dir.mkdir(parents=True, exist_ok=True)
                for fn in files:
                    if fn.lower().endswith((".ttf", ".otf")):
                        shutil.copy2(Path(root_dir)/fn, out_dir/fn)
            logs.append("📁 Copied local fonts → zip_last/fonts/")
        # Copy repository theme .sty next to tex and at root
        try:
            tmpl_dir = ROOT / "template"
            for sty in tmpl_dir.glob("*.sty"):
                shutil.copy2(sty, work_zip_dir / sty.name)
                shutil.copy2(sty, tex_path.parent / sty.name)
            logs.append("📄 Copied template/*.sty → zip_last/ and tex dir")
        except Exception as e:
            logs.append(f"⚠️ Copy sty failed: {e}")
    except Exception as e:
        logs.append(f"⚠️ Local font setup failed: {e}")

    # Compile to PDF
    pdf_path = _compile_tex_to_pdf(tex_path, logs)
    if not pdf_path or not pdf_path.exists():
        logs.append("❌ Failed to compile last pipeline zip PDF.")
        _write_logs(LOG_PATH, logs)
        return (
            "<div style='color:#b00'><b>Compile failed.</b></div>"
            + "<pre style='white-space:pre-wrap;background:#f7f7f8;padding:8px;border-radius:6px'>"
            + "\n".join(logs)
            + "</pre>",
            None,
        )
    try:
        b64 = base64.b64encode(pdf_path.read_bytes()).decode("utf-8")
        open_tab = f"<a target='_blank' rel='noopener' href='data:application/pdf;base64,{b64}'>Open PDF in new tab</a>"
        html = (
            f"<div style='margin-bottom:8px'>{open_tab}</div>"
            + _pdf_to_iframe_html(pdf_path, height="700px")
        )
        _write_logs(LOG_PATH, logs)
        return html, str(pdf_path)
    except Exception as e:
        logs.append(f"⚠️ preview failed: {e}")
        _write_logs(LOG_PATH, logs)
        return f"<div>Compiled but preview failed: {e}</div>", None

def debug_compile_uploaded_zip(zip_file):
    """Compile an uploaded poster zip (user-provided); return preview HTML + PDF path."""
    logs = [f"🐞 Debug(upload) at {_now_str()}"]
    if not zip_file:
        return "<div style='color:#b00'>Please upload a .zip file first.</div>", None
    # Prepare workspace
    run_id, WORK_DIR, LOG_PATH, _ = _prepare_workspace(logs)
    work_zip_dir = WORK_DIR / "zip_upload"
    work_zip_dir.mkdir(parents=True, exist_ok=True)
    # Save uploaded zip
    up_path = work_zip_dir / "input.zip"
    try:
        shutil.copy(zip_file.name, up_path)
    except Exception as e:
        logs.append(f"❌ save upload failed: {e}")
        _write_logs(LOG_PATH, logs)
        return "<div style='color:#b00'>Save upload failed.</div>", None
    # Extract
    try:
        import zipfile as _zf
        with _zf.ZipFile(up_path, 'r') as zf:
            zf.extractall(work_zip_dir)
    except Exception as e:
        logs.append(f"❌ unzip failed: {e}")
        _write_logs(LOG_PATH, logs)
        return "<div style='color:#b00'>Unzip failed.</div>", None
    # Find tex
    tex_path = None
    for name in ("poster_output.tex", "poster.tex"):
        cand = list(work_zip_dir.rglob(name))
        if cand:
            tex_path = cand[0]
            break
    if tex_path is None:
        cand = list(work_zip_dir.rglob("*.tex"))
        if cand:
            tex_path = cand[0]
    if tex_path is None:
        logs.append("❌ No .tex file found in uploaded zip")
        _write_logs(LOG_PATH, logs)
        return "<div style='color:#b00'>No .tex found in uploaded zip</div>"
    # Disable logoleft if missing
    try:
        logos_dir = tex_path.parent / "logos"
        has_left = False
        if logos_dir.exists():
            for p in logos_dir.iterdir():
                if p.is_file() and p.stem == "left_logo":
                    has_left = True
                    break
        if not has_left:
            txt = tex_path.read_text(encoding="utf-8")
            if "\\logoleft" in txt:
                import re as _re
                new_txt = _re.sub(r"^\\\s*logoleft\s*\{.*?\}\s*$", lambda m: "%" + m.group(0), txt, flags=_re.MULTILINE)
                if new_txt != txt:
                    tex_path.write_text(new_txt, encoding="utf-8")
                    logs.append("ℹ️ No left_logo found; disabled \\logoleft in uploaded project.")
    except Exception as e:
        logs.append(f"⚠️ left_logo adjust failed: {e}")
    # Compile
    pdf_path = _compile_tex_to_pdf(tex_path, logs)
    if not pdf_path or not pdf_path.exists():
        logs.append("❌ Failed to compile uploaded zip PDF.")
        _write_logs(LOG_PATH, logs)
        return (
            "<div style='color:#b00'><b>Compile failed.</b></div>"
            + "<pre style='white-space:pre-wrap;background:#f7f7f8;padding:8px;border-radius:6px'>"
            + "\n".join(logs)
            + "</pre>",
            None,
        )
    try:
        b64 = base64.b64encode(pdf_path.read_bytes()).decode("utf-8")
        open_tab = f"<a target='_blank' rel='noopener' href='data:application/pdf;base64,{b64}'>Open PDF in new tab</a>"
        html = (
            f"<div style='margin-bottom:8px'>{open_tab}</div>"
            + _pdf_to_iframe_html(pdf_path, height="700px")
        )
        _write_logs(LOG_PATH, logs)
        return "", str(pdf_path)
    except Exception as e:
        logs.append(f"⚠️ preview failed: {e}")
        _write_logs(LOG_PATH, logs)
        return f"<div>Compiled but preview failed: {e}</div>", None

def debug_compile_output_zip():
    """Compile the repo-root output.zip (a real LaTeX project) and preview the resulting PDF."""
    # Stage repo output.zip to runs/<id>/output.zip to follow pipeline layout, then delegate
    zip_path = ROOT / "output.zip"
    if not zip_path.exists():
        return (
            "<div style='color:#b00'><b>output.zip not found at repo root.</b></div>"
            + f"<div>Expected at: {zip_path}</div>",
            None,
        )
    logs = [f"🐞 Stage(repo zip) at {_now_str()}"]
    _, WORK_DIR, LOG_PATH, ZIP_PATH = _prepare_workspace(logs)
    try:
        shutil.copy2(zip_path, ZIP_PATH)
        logs.append(f"📦 Staged repo output.zip → runs/{WORK_DIR.name}/output.zip")
        _write_logs(LOG_PATH, logs)
    except Exception as e:
        logs.append(f"❌ Failed staging output.zip: {e}")
        _write_logs(LOG_PATH, logs)
        return "<div style='color:#b00'>Failed to stage output.zip</div>"
    return debug_compile_last_pipeline_zip()
    logs = [f"🐞 Debug(real) at {_now_str()}"]
    zip_path = ROOT / "output.zip"
    if not zip_path.exists():
        return (
            "<div style='color:#b00'><b>output.zip not found at repo root.</b></div>"
            + f"<div>Expected at: {zip_path}</div>"
        )

    # Prepare workspace
    run_id, WORK_DIR, LOG_PATH, _ = _prepare_workspace(logs)
    work_zip_dir = WORK_DIR / "zip_proj"
    work_zip_dir.mkdir(parents=True, exist_ok=True)
    logs.append(f"Workspace: runs/{WORK_DIR.name}")
    logs.append("Unzipping output.zip → zip_proj/")

    # Extract zip
    try:
        import zipfile as _zf
        with _zf.ZipFile(zip_path, 'r') as zf:
            zf.extractall(work_zip_dir)
    except Exception as e:
        logs.append(f"❌ unzip failed: {e}")
        _write_logs(LOG_PATH, logs)
        return "<div style='color:#b00'>Unzip failed.</div>", None

    # Locate poster_output.tex (fallback to poster.tex)
    tex_path = None
    for name in ("poster_output.tex", "poster.tex"):
        cand = list(work_zip_dir.rglob(name))
        if cand:
            tex_path = cand[0]
            break
    if tex_path is None:
        # fallback: any .tex
        cand = list(work_zip_dir.rglob("*.tex"))
        if cand:
            tex_path = cand[0]
    if tex_path is None:
        logs.append("❌ No .tex file found in output.zip")
        _write_logs(LOG_PATH, logs)
        return "<div style='color:#b00'>No .tex found in output.zip</div>", None

    # If left_logo missing, disable \logoleft
    try:
        logos_dir = tex_path.parent / "logos"
        has_left = False
        if logos_dir.exists():
            for p in logos_dir.iterdir():
                if p.is_file() and p.stem == "left_logo":
                    has_left = True
                    break
        if not has_left:
            txt = tex_path.read_text(encoding="utf-8")
            if "\\logoleft" in txt:
                import re as _re
                new_txt = _re.sub(r"^\\\s*logoleft\s*\{.*?\}\s*$", lambda m: "%" + m.group(0), txt, flags=_re.MULTILINE)
                if new_txt != txt:
                    tex_path.write_text(new_txt, encoding="utf-8")
                    logs.append("ℹ️ No left_logo found; disabled \\logoleft in zip project.")
    except Exception as e:
        logs.append(f"⚠️ left_logo adjust failed: {e}")

    # Compile to PDF
    pdf_path = _compile_tex_to_pdf(tex_path, logs)
    if not pdf_path or not pdf_path.exists():
        logs.append("❌ Failed to compile zip PDF.")
        _write_logs(LOG_PATH, logs)
        return (
            "<div style='color:#b00'><b>Compile failed.</b></div>"
            + "<pre style='white-space:pre-wrap;background:#f7f7f8;padding:8px;border-radius:6px'>"
            + "\n".join(logs)
            + "</pre>",
            None,
        )

    try:
        b64 = base64.b64encode(pdf_path.read_bytes()).decode("utf-8")
        open_tab = f"<a target='_blank' rel='noopener' href='data:application/pdf;base64,{b64}'>Open PDF in new tab</a>"
        html = (
            f"<div style='margin-bottom:8px'>{open_tab}</div>"
            + _pdf_to_iframe_html(pdf_path, height="700px")
        )
        _write_logs(LOG_PATH, logs)
        return html, str(pdf_path)
    except Exception as e:
        logs.append(f"⚠️ preview failed: {e}")
        _write_logs(LOG_PATH, logs)
        return f"<div>Compiled but preview failed: {e}</div>", None

def _find_last_pipeline_zip():
    try:
        candidates = []
        for d in RUNS_DIR.iterdir():
            try:
                if d.is_dir():
                    z = d / "output.zip"
                    if z.exists():
                        candidates.append((z.stat().st_mtime, z))
            except Exception:
                pass
        if not candidates:
            return None
        candidates.sort(key=lambda x: x[0], reverse=True)
        return candidates[0][1]
    except Exception:
        return None

def debug_compile_last_pipeline_zip():
    """Find the most recent runs/*/output.zip from pipeline, compile, and return preview HTML + PDF path."""
    logs = [f"🐞 Debug(last-pipeline-zip) at {_now_str()}"]
    last_zip = _find_last_pipeline_zip()
    if not last_zip:
        repo_zip = ROOT / "output.zip"
        if repo_zip.exists():
            try:
                _, W, L, Z = _prepare_workspace(logs)
                shutil.copy2(repo_zip, Z)
                logs.append(f"📦 Auto-staged repo output.zip → runs/{W.name}/output.zip")
                last_zip = Z
            except Exception as e:
                logs.append(f"❌ Auto-stage failed: {e}")
                return "<div style='color:#b00'>No recent pipeline output.zip found and auto-stage failed.</div>"
        else:
            return "<div style='color:#b00'>No recent pipeline output.zip found under runs/.</div>", None

    # Prepare workspace
    run_id, WORK_DIR, LOG_PATH, _ = _prepare_workspace(logs)
    work_zip_dir = WORK_DIR / "zip_last"
    work_zip_dir.mkdir(parents=True, exist_ok=True)
    logs.append(f"Workspace: runs/{WORK_DIR.name}")
    logs.append(f"Using: {last_zip}")

    # Extract zip
    try:
        import zipfile as _zf
        with _zf.ZipFile(last_zip, 'r') as zf:
            zf.extractall(work_zip_dir)
    except Exception as e:
        logs.append(f"❌ unzip failed: {e}")
        _write_logs(LOG_PATH, logs)
        return "<div style='color:#b00'>Unzip failed.</div>", None

    # Locate tex
    tex_path = None
    for name in ("poster_output.tex", "poster.tex"):
        cand = list(work_zip_dir.rglob(name))
        if cand:
            tex_path = cand[0]
            break
    if tex_path is None:
        cand = list(work_zip_dir.rglob("*.tex"))
        if cand:
            tex_path = cand[0]
    if tex_path is None:
        logs.append("❌ No .tex file found in last pipeline zip")
        _write_logs(LOG_PATH, logs)
        return "<div style='color:#b00'>No .tex found in last pipeline zip</div>", None

    # Ensure local fonts and theme precedence (same as other debug path)
    try:
        src_fonts = ROOT / "template" / "fonts"
        dst_fonts = work_zip_dir / "fonts"
        if src_fonts.exists():
            for root_dir, dirs, files in os.walk(src_fonts):
                rel = Path(root_dir).relative_to(src_fonts)
                out_dir = dst_fonts / rel
                out_dir.mkdir(parents=True, exist_ok=True)
                for fn in files:
                    if fn.lower().endswith((".ttf", ".otf")):
                        shutil.copy2(Path(root_dir)/fn, out_dir/fn)
            logs.append("📁 Copied local fonts → zip_last/fonts/")
        # Copy repository theme .sty next to tex and at root
        try:
            tmpl_dir = ROOT / "template"
            for sty in tmpl_dir.glob("*.sty"):
                shutil.copy2(sty, work_zip_dir / sty.name)
                shutil.copy2(sty, tex_path.parent / sty.name)
            logs.append("📄 Copied template/*.sty → zip_last/ and tex dir")
        except Exception as e:
            logs.append(f"⚠️ Copy sty failed: {e}")
    except Exception as e:
        logs.append(f"⚠️ Local font setup failed: {e}")

    # Compile to PDF
    pdf_path = _compile_tex_to_pdf(tex_path, logs)
    if not pdf_path or not pdf_path.exists():
        logs.append("❌ Failed to compile last pipeline zip PDF.")
        _write_logs(LOG_PATH, logs)
        return (
            "<div style='color:#b00'><b>Compile failed.</b></div>"
            + "<pre style='white-space:pre-wrap;background:#f7f7f8;padding:8px;border-radius:6px'>"
            + "\n".join(logs)
            + "</pre>",
            None,
        )
    try:
        b64 = base64.b64encode(pdf_path.read_bytes()).decode("utf-8")
        open_tab = f"<a target='_blank' rel='noopener' href='data:application/pdf;base64,{b64}'>Open PDF in new tab</a>"
        html = (
            f"<div style='margin-bottom:8px'>{open_tab}</div>"
            + _pdf_to_iframe_html(pdf_path, height="700px")
        )
        _write_logs(LOG_PATH, logs)
        return html, str(pdf_path)
    except Exception as e:
        logs.append(f"⚠️ preview failed: {e}")
        _write_logs(LOG_PATH, logs)
        return f"<div>Compiled but preview failed: {e}</div>", None

def debug_compile_uploaded_zip(zip_file):
    """Compile an uploaded poster zip (user-provided); return preview HTML + PDF path."""
    logs = [f"🐞 Debug(upload) at {_now_str()}"]
    if not zip_file:
        return "<div style='color:#b00'>Please upload a .zip file first.</div>", None
    # Prepare workspace
    run_id, WORK_DIR, LOG_PATH, _ = _prepare_workspace(logs)
    work_zip_dir = WORK_DIR / "zip_upload"
    work_zip_dir.mkdir(parents=True, exist_ok=True)
    # Save uploaded zip
    up_path = work_zip_dir / "input.zip"
    try:
        shutil.copy(zip_file.name, up_path)
    except Exception as e:
        logs.append(f"❌ save upload failed: {e}")
        _write_logs(LOG_PATH, logs)
        return "<div style='color:#b00'>Save upload failed.</div>", None
    # Extract
    try:
        import zipfile as _zf
        with _zf.ZipFile(up_path, 'r') as zf:
            zf.extractall(work_zip_dir)
    except Exception as e:
        logs.append(f"❌ unzip failed: {e}")
        _write_logs(LOG_PATH, logs)
        return "<div style='color:#b00'>Unzip failed.</div>", None
    # Find tex
    tex_path = None
    for name in ("poster_output.tex", "poster.tex"):
        cand = list(work_zip_dir.rglob(name))
        if cand:
            tex_path = cand[0]
            break
    if tex_path is None:
        cand = list(work_zip_dir.rglob("*.tex"))
        if cand:
            tex_path = cand[0]
    if tex_path is None:
        logs.append("❌ No .tex file found in uploaded zip")
        _write_logs(LOG_PATH, logs)
        return "<div style='color:#b00'>No .tex found in uploaded zip</div>"
    # Disable logoleft if missing
    try:
        logos_dir = tex_path.parent / "logos"
        has_left = False
        if logos_dir.exists():
            for p in logos_dir.iterdir():
                if p.is_file() and p.stem == "left_logo":
                    has_left = True
                    break
        if not has_left:
            txt = tex_path.read_text(encoding="utf-8")
            if "\\logoleft" in txt:
                import re as _re
                new_txt = _re.sub(r"^\\\s*logoleft\s*\{.*?\}\s*$", lambda m: "%" + m.group(0), txt, flags=_re.MULTILINE)
                if new_txt != txt:
                    tex_path.write_text(new_txt, encoding="utf-8")
                    logs.append("ℹ️ No left_logo found; disabled \\logoleft in uploaded project.")
    except Exception as e:
        logs.append(f"⚠️ left_logo adjust failed: {e}")
    # Compile
    pdf_path = _compile_tex_to_pdf(tex_path, logs)
    if not pdf_path or not pdf_path.exists():
        logs.append("❌ Failed to compile uploaded zip PDF.")
        _write_logs(LOG_PATH, logs)
        return (
            "<div style='color:#b00'><b>Compile failed.</b></div>"
            + "<pre style='white-space:pre-wrap;background:#f7f7f8;padding:8px;border-radius:6px'>"
            + "\n".join(logs)
            + "</pre>",
            None,
        )
    try:
        b64 = base64.b64encode(pdf_path.read_bytes()).decode("utf-8")
        open_tab = f"<a target='_blank' rel='noopener' href='data:application/pdf;base64,{b64}'>Open PDF in new tab</a>"
        html = (
            f"<div style='margin-bottom:8px'>{open_tab}</div>"
            + _pdf_to_iframe_html(pdf_path, height="700px")
        )
        _write_logs(LOG_PATH, logs)
        return "", str(pdf_path)
    except Exception as e:
        logs.append(f"⚠️ preview failed: {e}")
        _write_logs(LOG_PATH, logs)
        return f"<div>Compiled but preview failed: {e}</div>", None

def debug_compile_output_zip():
    """Compile the repo-root output.zip (a real LaTeX project) and preview the resulting PDF."""
    # Stage repo output.zip to runs/<id>/output.zip to follow pipeline layout, then delegate
    zip_path = ROOT / "output.zip"
    if not zip_path.exists():
        return (
            "<div style='color:#b00'><b>output.zip not found at repo root.</b></div>"
            + f"<div>Expected at: {zip_path}</div>",
            None,
        )
    logs = [f"🐞 Stage(repo zip) at {_now_str()}"]
    _, WORK_DIR, LOG_PATH, ZIP_PATH = _prepare_workspace(logs)
    try:
        shutil.copy2(zip_path, ZIP_PATH)
        logs.append(f"📦 Staged repo output.zip → runs/{WORK_DIR.name}/output.zip")
        _write_logs(LOG_PATH, logs)
    except Exception as e:
        logs.append(f"❌ Failed staging output.zip: {e}")
        _write_logs(LOG_PATH, logs)
        return "<div style='color:#b00'>Failed to stage output.zip</div>"
    return debug_compile_last_pipeline_zip()
    logs = [f"🐞 Debug(real) at {_now_str()}"]
    zip_path = ROOT / "output.zip"
    if not zip_path.exists():
        return (
            "<div style='color:#b00'><b>output.zip not found at repo root.</b></div>"
            + f"<div>Expected at: {zip_path}</div>",
            None,
        )

    # Prepare workspace
    run_id, WORK_DIR, LOG_PATH, _ = _prepare_workspace(logs)
    work_zip_dir = WORK_DIR / "zip_proj"
    work_zip_dir.mkdir(parents=True, exist_ok=True)
    logs.append(f"Workspace: runs/{WORK_DIR.name}")
    logs.append("Unzipping output.zip → zip_proj/")

    # Extract zip
    try:
        import zipfile as _zf
        with _zf.ZipFile(zip_path, 'r') as zf:
            zf.extractall(work_zip_dir)
    except Exception as e:
        logs.append(f"❌ unzip failed: {e}")
        _write_logs(LOG_PATH, logs)
        return "<div style='color:#b00'>Unzip failed.</div>", None

    # Locate poster_output.tex (fallback to poster.tex)
    tex_path = None
    for name in ("poster_output.tex", "poster.tex"):
        cand = list(work_zip_dir.rglob(name))
        if cand:
            tex_path = cand[0]
            break
    if tex_path is None:
        # fallback: any .tex
        cand = list(work_zip_dir.rglob("*.tex"))
        if cand:
            tex_path = cand[0]
    if tex_path is None:
        logs.append("❌ No .tex file found in output.zip")
        _write_logs(LOG_PATH, logs)
        return "<div style='color:#b00'>No .tex found in output.zip</div>", None

    # If left_logo missing, disable \logoleft
    try:
        logos_dir = tex_path.parent / "logos"
        has_left = False
        if logos_dir.exists():
            for p in logos_dir.iterdir():
                if p.is_file() and p.stem == "left_logo":
                    has_left = True
                    break
        if not has_left:
            txt = tex_path.read_text(encoding="utf-8")
            if "\\logoleft" in txt:
                import re as _re
                new_txt = _re.sub(r"^\\\s*logoleft\s*\{.*?\}\s*$", lambda m: "%" + m.group(0), txt, flags=_re.MULTILINE)
                if new_txt != txt:
                    tex_path.write_text(new_txt, encoding="utf-8")
                    logs.append("ℹ️ No left_logo found; disabled \\logoleft in zip project.")
    except Exception as e:
        logs.append(f"⚠️ left_logo adjust failed: {e}")

    # Compile to PDF
    pdf_path = _compile_tex_to_pdf(tex_path, logs)
    if not pdf_path or not pdf_path.exists():
        logs.append("❌ Failed to compile zip PDF.")
        _write_logs(LOG_PATH, logs)
        return (
            "<div style='color:#b00'><b>Compile failed.</b></div>"
            + "<pre style='white-space:pre-wrap;background:#f7f7f8;padding:8px;border-radius:6px'>"
            + "\n".join(logs)
            + "</pre>",
            None,
        )

    try:
        b64 = base64.b64encode(pdf_path.read_bytes()).decode("utf-8")
        open_tab = f"<a target='_blank' rel='noopener' href='data:application/pdf;base64,{b64}'>Open PDF in new tab</a>"
        html = (
            f"<div style='margin-bottom:8px'>{open_tab}</div>"
            + _pdf_to_iframe_html(pdf_path, height="700px")
        )
        _write_logs(LOG_PATH, logs)
        return html, str(pdf_path)
    except Exception as e:
        logs.append(f"⚠️ preview failed: {e}")
        _write_logs(LOG_PATH, logs)
        return f"<div>Compiled but preview failed: {e}</div>", None

def _find_last_pipeline_zip():
    try:
        candidates = []
        for d in RUNS_DIR.iterdir():
            try:
                if d.is_dir():
                    z = d / "output.zip"
                    if z.exists():
                        candidates.append((z.stat().st_mtime, z))
            except Exception:
                pass
        if not candidates:
            return None
        candidates.sort(key=lambda x: x[0], reverse=True)
        return candidates[0][1]
    except Exception:
        return None

def debug_compile_last_pipeline_zip():
    """Find the most recent runs/*/output.zip from pipeline, compile, and return preview HTML + PDF path."""
    logs = [f"🐞 Debug(last-pipeline-zip) at {_now_str()}"]
    last_zip = _find_last_pipeline_zip()
    if not last_zip:
        repo_zip = ROOT / "output.zip"
        if repo_zip.exists():
            try:
                _, W, L, Z = _prepare_workspace(logs)
                shutil.copy2(repo_zip, Z)
                logs.append(f"📦 Auto-staged repo output.zip → runs/{W.name}/output.zip")
                last_zip = Z
            except Exception as e:
                logs.append(f"❌ Auto-stage failed: {e}")
                return "<div style='color:#b00'>No recent pipeline output.zip found and auto-stage failed.</div>"
        else:
            return "<div style='color:#b00'>No recent pipeline output.zip found under runs/.</div>", None

    # Prepare workspace
    run_id, WORK_DIR, LOG_PATH, _ = _prepare_workspace(logs)
    work_zip_dir = WORK_DIR / "zip_last"
    work_zip_dir.mkdir(parents=True, exist_ok=True)
    logs.append(f"Workspace: runs/{WORK_DIR.name}")
    logs.append(f"Using: {last_zip}")

    # Extract zip
    try:
        import zipfile as _zf
        with _zf.ZipFile(last_zip, 'r') as zf:
            zf.extractall(work_zip_dir)
    except Exception as e:
        logs.append(f"❌ unzip failed: {e}")
        _write_logs(LOG_PATH, logs)
        return "<div style='color:#b00'>Unzip failed.</div>", None

    # Locate tex
    tex_path = None
    for name in ("poster_output.tex", "poster.tex"):
        cand = list(work_zip_dir.rglob(name))
        if cand:
            tex_path = cand[0]
            break
    if tex_path is None:
        cand = list(work_zip_dir.rglob("*.tex"))
        if cand:
            tex_path = cand[0]
    if tex_path is None:
        logs.append("❌ No .tex file found in last pipeline zip")
        _write_logs(LOG_PATH, logs)
        return "<div style='color:#b00'>No .tex found in last pipeline zip</div>", None

    # Ensure local fonts and theme precedence (same as other debug path)
    try:
        src_fonts = ROOT / "template" / "fonts"
        dst_fonts = work_zip_dir / "fonts"
        if src_fonts.exists():
            for root_dir, dirs, files in os.walk(src_fonts):
                rel = Path(root_dir).relative_to(src_fonts)
                out_dir = dst_fonts / rel
                out_dir.mkdir(parents=True, exist_ok=True)
                for fn in files:
                    if fn.lower().endswith((".ttf", ".otf")):
                        shutil.copy2(Path(root_dir)/fn, out_dir/fn)
            logs.append("📁 Copied local fonts → zip_last/fonts/")
        # Copy repository theme .sty next to tex and at root
        try:
            tmpl_dir = ROOT / "template"
            for sty in tmpl_dir.glob("*.sty"):
                shutil.copy2(sty, work_zip_dir / sty.name)
                shutil.copy2(sty, tex_path.parent / sty.name)
            logs.append("📄 Copied template/*.sty → zip_last/ and tex dir")
        except Exception as e:
            logs.append(f"⚠️ Copy sty failed: {e}")
    except Exception as e:
        logs.append(f"⚠️ Local font setup failed: {e}")

    # Compile to PDF
    pdf_path = _compile_tex_to_pdf(tex_path, logs)
    if not pdf_path or not pdf_path.exists():
        logs.append("❌ Failed to compile last pipeline zip PDF.")
        _write_logs(LOG_PATH, logs)
        return (
            "<div style='color:#b00'><b>Compile failed.</b></div>"
            + "<pre style='white-space:pre-wrap;background:#f7f7f8;padding:8px;border-radius:6px'>"
            + "\n".join(logs)
            + "</pre>",
            None,
        )
    try:
        b64 = base64.b64encode(pdf_path.read_bytes()).decode("utf-8")
        open_tab = f"<a target='_blank' rel='noopener' href='data:application/pdf;base64,{b64}'>Open PDF in new tab</a>"
        html = (
            f"<div style='margin-bottom:8px'>{open_tab}</div>"
            + _pdf_to_iframe_html(pdf_path, height="700px")
        )
        _write_logs(LOG_PATH, logs)
        return html, str(pdf_path)
    except Exception as e:
        logs.append(f"⚠️ preview failed: {e}")
        _write_logs(LOG_PATH, logs)
        return f"<div>Compiled but preview failed: {e}</div>", None

def debug_compile_uploaded_zip(zip_file):
    """Compile an uploaded poster zip (user-provided); return preview HTML + PDF path."""
    logs = [f"🐞 Debug(upload) at {_now_str()}"]
    if not zip_file:
        return "<div style='color:#b00'>Please upload a .zip file first.</div>", None
    # Prepare workspace
    run_id, WORK_DIR, LOG_PATH, _ = _prepare_workspace(logs)
    work_zip_dir = WORK_DIR / "zip_upload"
    work_zip_dir.mkdir(parents=True, exist_ok=True)
    # Save uploaded zip
    up_path = work_zip_dir / "input.zip"
    try:
        shutil.copy(zip_file.name, up_path)
    except Exception as e:
        logs.append(f"❌ save upload failed: {e}")
        _write_logs(LOG_PATH, logs)
        return "<div style='color:#b00'>Save upload failed.</div>", None
    # Extract
    try:
        import zipfile as _zf
        with _zf.ZipFile(up_path, 'r') as zf:
            zf.extractall(work_zip_dir)
    except Exception as e:
        logs.append(f"❌ unzip failed: {e}")
        _write_logs(LOG_PATH, logs)
        return "<div style='color:#b00'>Unzip failed.</div>", None
    # Find tex
    tex_path = None
    for name in ("poster_output.tex", "poster.tex"):
        cand = list(work_zip_dir.rglob(name))
        if cand:
            tex_path = cand[0]
            break
    if tex_path is None:
        cand = list(work_zip_dir.rglob("*.tex"))
        if cand:
            tex_path = cand[0]
    if tex_path is None:
        logs.append("❌ No .tex file found in uploaded zip")
        _write_logs(LOG_PATH, logs)
        return "<div style='color:#b00'>No .tex found in uploaded zip</div>"
    # Disable logoleft if missing
    try:
        logos_dir = tex_path.parent / "logos"
        has_left = False
        if logos_dir.exists():
            for p in logos_dir.iterdir():
                if p.is_file() and p.stem == "left_logo":
                    has_left = True
                    break
        if not has_left:
            txt = tex_path.read_text(encoding="utf-8")
            if "\\logoleft" in txt:
                import re as _re
                new_txt = _re.sub(r"^\\\s*logoleft\s*\{.*?\}\s*$", lambda m: "%" + m.group(0), txt, flags=_re.MULTILINE)
                if new_txt != txt:
                    tex_path.write_text(new_txt, encoding="utf-8")
                    logs.append("ℹ️ No left_logo found; disabled \\logoleft in uploaded project.")
    except Exception as e:
        logs.append(f"⚠️ left_logo adjust failed: {e}")
    # Compile
    pdf_path = _compile_tex_to_pdf(tex_path, logs)
    if not pdf_path or not pdf_path.exists():
        logs.append("❌ Failed to compile uploaded zip PDF.")
        _write_logs(LOG_PATH, logs)
        return (
            "<div style='color:#b00'><b>Compile failed.</b></div>"
            + "<pre style='white-space:pre-wrap;background:#f7f7f8;padding:8px;border-radius:6px'>"
            + "\n".join(logs)
            + "</pre>",
            None,
        )
    try:
        b64 = base64.b64encode(pdf_path.read_bytes()).decode("utf-8")
        open_tab = f"<a target='_blank' rel='noopener' href='data:application/pdf;base64,{b64}'>Open PDF in new tab</a>"
        html = (
            f"<div style='margin-bottom:8px'>{open_tab}</div>"
            + _pdf_to_iframe_html(pdf_path, height="700px")
        )
        _write_logs(LOG_PATH, logs)
        return "", str(pdf_path)
    except Exception as e:
        logs.append(f"⚠️ preview failed: {e}")
        _write_logs(LOG_PATH, logs)
        return f"<div>Compiled but preview failed: {e}</div>", None

def debug_compile_output_zip():
    """Compile the repo-root output.zip (a real LaTeX project) and preview the resulting PDF."""
    # Stage repo output.zip to runs/<id>/output.zip to follow pipeline layout, then delegate
    zip_path = ROOT / "output.zip"
    if not zip_path.exists():
        return (
            "<div style='color:#b00'><b>output.zip not found at repo root.</b></div>"
            + f"<div>Expected at: {zip_path}</div>",
            None,
        )
    logs = [f"🐞 Stage(repo zip) at {_now_str()}"]
    _, WORK_DIR, LOG_PATH, ZIP_PATH = _prepare_workspace(logs)
    try:
        shutil.copy2(zip_path, ZIP_PATH)
        logs.append(f"📦 Staged repo output.zip → runs/{WORK_DIR.name}/output.zip")
        _write_logs(LOG_PATH, logs)
    except Exception as e:
        logs.append(f"❌ Failed staging output.zip: {e}")
        _write_logs(LOG_PATH, logs)
        return "<div style='color:#b00'>Failed to stage output.zip</div>"
    return debug_compile_last_pipeline_zip()
    logs = [f"🐞 Debug(real) at {_now_str()}"]
    zip_path = ROOT / "output.zip"
    if not zip_path.exists():
        return (
            "<div style='color:#b00'><b>output.zip not found at repo root.</b></div>"
            + f"<div>Expected at: {zip_path}</div>",
            None,
        )

    # Prepare workspace
    run_id, WORK_DIR, LOG_PATH, _ = _prepare_workspace(logs)
    work_zip_dir = WORK_DIR / "zip_proj"
    work_zip_dir.mkdir(parents=True, exist_ok=True)
    logs.append(f"Workspace: runs/{WORK_DIR.name}")
    logs.append("Unzipping output.zip → zip_proj/")

    # Extract zip
    try:
        import zipfile as _zf
        with _zf.ZipFile(zip_path, 'r') as zf:
            zf.extractall(work_zip_dir)
    except Exception as e:
        logs.append(f"❌ unzip failed: {e}")
        _write_logs(LOG_PATH, logs)
        return "<div style='color:#b00'>Unzip failed.</div>", None

    # Locate poster_output.tex (fallback to poster.tex)
    tex_path = None
    for name in ("poster_output.tex", "poster.tex"):
        cand = list(work_zip_dir.rglob(name))
        if cand:
            tex_path = cand[0]
            break
    if tex_path is None:
        # fallback: any .tex
        cand = list(work_zip_dir.rglob("*.tex"))
        if cand:
            tex_path = cand[0]
    if tex_path is None:
        logs.append("❌ No .tex file found in output.zip")
        _write_logs(LOG_PATH, logs)
        return "<div style='color:#b00'>No .tex found in output.zip</div>", None

    # If left_logo missing, disable \logoleft
    try:
        logos_dir = tex_path.parent / "logos"
        has_left = False
        if logos_dir.exists():
            for p in logos_dir.iterdir():
                if p.is_file() and p.stem == "left_logo":
                    has_left = True
                    break
        if not has_left:
            txt = tex_path.read_text(encoding="utf-8")
            if "\\logoleft" in txt:
                import re as _re
                new_txt = _re.sub(r"^\\\s*logoleft\s*\{.*?\}\s*$", lambda m: "%" + m.group(0), txt, flags=_re.MULTILINE)
                if new_txt != txt:
                    tex_path.write_text(new_txt, encoding="utf-8")
                    logs.append("ℹ️ No left_logo found; disabled \\logoleft in zip project.")
    except Exception as e:
        logs.append(f"⚠️ left_logo adjust failed: {e}")

    # Compile to PDF
    pdf_path = _compile_tex_to_pdf(tex_path, logs)
    if not pdf_path or not pdf_path.exists():
        logs.append("❌ Failed to compile zip PDF.")
        _write_logs(LOG_PATH, logs)
        return (
            "<div style='color:#b00'><b>Compile failed.</b></div>"
            + "<pre style='white-space:pre-wrap;background:#f7f7f8;padding:8px;border-radius:6px'>"
            + "\n".join(logs)
            + "</pre>",
            None,
        )

    try:
        b64 = base64.b64encode(pdf_path.read_bytes()).decode("utf-8")
        open_tab = f"<a target='_blank' rel='noopener' href='data:application/pdf;base64,{b64}'>Open PDF in new tab</a>"
        html = (
            f"<div style='margin-bottom:8px'>{open_tab}</div>"
            + _pdf_to_iframe_html(pdf_path, height="700px")
        )
        _write_logs(LOG_PATH, logs)
        return html, str(pdf_path)
    except Exception as e:
        logs.append(f"⚠️ preview failed: {e}")
        _write_logs(LOG_PATH, logs)
        return f"<div>Compiled but preview failed: {e}</div>", None

def _find_last_pipeline_zip():
    try:
        candidates = []
        for d in RUNS_DIR.iterdir():
            try:
                if d.is_dir():
                    z = d / "output.zip"
                    if z.exists():
                        candidates.append((z.stat().st_mtime, z))
            except Exception:
                pass
        if not candidates:
            return None
        candidates.sort(key=lambda x: x[0], reverse=True)
        return candidates[0][1]
    except Exception:
        return None

def debug_compile_last_pipeline_zip():
    """Find the most recent runs/*/output.zip from pipeline, compile, and return preview HTML + PDF path."""
    logs = [f"🐞 Debug(last-pipeline-zip) at {_now_str()}"]
    last_zip = _find_last_pipeline_zip()
    if not last_zip:
        repo_zip = ROOT / "output.zip"
        if repo_zip.exists():
            try:
                _, W, L, Z = _prepare_workspace(logs)
                shutil.copy2(repo_zip, Z)
                logs.append(f"📦 Auto-staged repo output.zip → runs/{W.name}/output.zip")
                last_zip = Z
            except Exception as e:
                logs.append(f"❌ Auto-stage failed: {e}")
                return "<div style='color:#b00'>No recent pipeline output.zip found and auto-stage failed.</div>"
        else:
            return "<div style='color:#b00'>No recent pipeline output.zip found under runs/.</div>", None

    # Prepare workspace
    run_id, WORK_DIR, LOG_PATH, _ = _prepare_workspace(logs)
    work_zip_dir = WORK_DIR / "zip_last"
    work_zip_dir.mkdir(parents=True, exist_ok=True)
    logs.append(f"Workspace: runs/{WORK_DIR.name}")
    logs.append(f"Using: {last_zip}")

    # Extract zip
    try:
        import zipfile as _zf
        with _zf.ZipFile(last_zip, 'r') as zf:
            zf.extractall(work_zip_dir)
    except Exception as e:
        logs.append(f"❌ unzip failed: {e}")
        _write_logs(LOG_PATH, logs)
        return "<div style='color:#b00'>Unzip failed.</div>", None

    # Locate tex
    tex_path = None
    for name in ("poster_output.tex", "poster.tex"):
        cand = list(work_zip_dir.rglob(name))
        if cand:
            tex_path = cand[0]
            break
    if tex_path is None:
        cand = list(work_zip_dir.rglob("*.tex"))
        if cand:
            tex_path = cand[0]
    if tex_path is None:
        logs.append("❌ No .tex file found in last pipeline zip")
        _write_logs(LOG_PATH, logs)
        return "<div style='color:#b00'>No .tex found in last pipeline zip</div>", None

    # Ensure local fonts and theme precedence (same as other debug path)
    try:
        src_fonts = ROOT / "template" / "fonts"
        dst_fonts = work_zip_dir / "fonts"
        if src_fonts.exists():
            for root_dir, dirs, files in os.walk(src_fonts):
                rel = Path(root_dir).relative_to(src_fonts)
                out_dir = dst_fonts / rel
                out_dir.mkdir(parents=True, exist_ok=True)
                for fn in files:
                    if fn.lower().endswith((".ttf", ".otf")):
                        shutil.copy2(Path(root_dir)/fn, out_dir/fn)
            logs.append("📁 Copied local fonts → zip_last/fonts/")
        # Copy repository theme .sty next to tex and at root
        try:
            tmpl_dir = ROOT / "template"
            for sty in tmpl_dir.glob("*.sty"):
                shutil.copy2(sty, work_zip_dir / sty.name)
                shutil.copy2(sty, tex_path.parent / sty.name)
            logs.append("📄 Copied template/*.sty → zip_last/ and tex dir")
        except Exception as e:
            logs.append(f"⚠️ Copy sty failed: {e}")
    except Exception as e:
        logs.append(f"⚠️ Local font setup failed: {e}")

    # Compile to PDF
    pdf_path = _compile_tex_to_pdf(tex_path, logs)
    if not pdf_path or not pdf_path.exists():
        logs.append("❌ Failed to compile last pipeline zip PDF.")
        _write_logs(LOG_PATH, logs)
        return (
            "<div style='color:#b00'><b>Compile failed.</b></div>"
            + "<pre style='white-space:pre-wrap;background:#f7f7f8;padding:8px;border-radius:6px'>"
            + "\n".join(logs)
            + "</pre>",
            None,
        )
    try:
        b64 = base64.b64encode(pdf_path.read_bytes()).decode("utf-8")
        open_tab = f"<a target='_blank' rel='noopener' href='data:application/pdf;base64,{b64}'>Open PDF in new tab</a>"
        html = (
            f"<div style='margin-bottom:8px'>{open_tab}</div>"
            + _pdf_to_iframe_html(pdf_path, height="700px")
        )
        _write_logs(LOG_PATH, logs)
        return html, str(pdf_path)
    except Exception as e:
        logs.append(f"⚠️ preview failed: {e}")
        _write_logs(LOG_PATH, logs)
        return f"<div>Compiled but preview failed: {e}</div>", None

def debug_compile_uploaded_zip(zip_file):
    """Compile an uploaded poster zip (user-provided); return preview HTML + PDF path."""
    logs = [f"🐞 Debug(upload) at {_now_str()}"]
    if not zip_file:
        return "<div style='color:#b00'>Please upload a .zip file first.</div>", None
    # Prepare workspace
    run_id, WORK_DIR, LOG_PATH, _ = _prepare_workspace(logs)
    work_zip_dir = WORK_DIR / "zip_upload"
    work_zip_dir.mkdir(parents=True, exist_ok=True)
    # Save uploaded zip
    up_path = work_zip_dir / "input.zip"
    try:
        shutil.copy(zip_file.name, up_path)
    except Exception as e:
        logs.append(f"❌ save upload failed: {e}")
        _write_logs(LOG_PATH, logs)
        return "<div style='color:#b00'>Save upload failed.</div>", None
    # Extract
    try:
        import zipfile as _zf
        with _zf.ZipFile(up_path, 'r') as zf:
            zf.extractall(work_zip_dir)
    except Exception as e:
        logs.append(f"❌ unzip failed: {e}")
        _write_logs(LOG_PATH, logs)
        return "<div style='color:#b00'>Unzip failed.</div>", None
    # Find tex
    tex_path = None
    for name in ("poster_output.tex", "poster.tex"):
        cand = list(work_zip_dir.rglob(name))
        if cand:
            tex_path = cand[0]
            break
    if tex_path is None:
        cand = list(work_zip_dir.rglob("*.tex"))
        if cand:
            tex_path = cand[0]
    if tex_path is None:
        logs.append("❌ No .tex file found in uploaded zip")
        _write_logs(LOG_PATH, logs)
        return "<div style='color:#b00'>No .tex found in uploaded zip</div>"
    # Disable logoleft if missing
    try:
        logos_dir = tex_path.parent / "logos"
        has_left = False
        if logos_dir.exists():
            for p in logos_dir.iterdir():
                if p.is_file() and p.stem == "left_logo":
                    has_left = True
                    break
        if not has_left:
            txt = tex_path.read_text(encoding="utf-8")
            if "\\logoleft" in txt:
                import re as _re
                new_txt = _re.sub(r"^\\\s*logoleft\s*\{.*?\}\s*$", lambda m: "%" + m.group(0), txt, flags=_re.MULTILINE)
                if new_txt != txt:
                    tex_path.write_text(new_txt, encoding="utf-8")
                    logs.append("ℹ️ No left_logo found; disabled \\logoleft in uploaded project.")
    except Exception as e:
        logs.append(f"⚠️ left_logo adjust failed: {e}")
    # Compile
    pdf_path = _compile_tex_to_pdf(tex_path, logs)
    if not pdf_path or not pdf_path.exists():
        logs.append("❌ Failed to compile uploaded zip PDF.")
        _write_logs(LOG_PATH, logs)
        return (
            "<div style='color:#b00'><b>Compile failed.</b></div>"
            + "<pre style='white-space:pre-wrap;background:#f7f7f8;padding:8px;border-radius:6px'>"
            + "\n".join(logs)
            + "</pre>",
            None,
        )
    try:
        b64 = base64.b64encode(pdf_path.read_bytes()).decode("utf-8")
        open_tab = f"<a target='_blank' rel='noopener' href='data:application/pdf;base64,{b64}'>Open PDF in new tab</a>"
        html = (
            f"<div style='margin-bottom:8px'>{open_tab}</div>"
            + _pdf_to_iframe_html(pdf_path, height="700px")
        )
        _write_logs(LOG_PATH, logs)
        return "", str(pdf_path)
    except Exception as e:
        logs.append(f"⚠️ preview failed: {e}")
        _write_logs(LOG_PATH, logs)
        return f"<div>Compiled but preview failed: {e}</div>", None

def debug_compile_output_zip():
    """Compile the repo-root output.zip (a real LaTeX project) and preview the resulting PDF."""
    # Stage repo output.zip to runs/<id>/output.zip to follow pipeline layout, then delegate
    zip_path = ROOT / "output.zip"
    if not zip_path.exists():
        return (
            "<div style='color:#b00'><b>output.zip not found at repo root.</b></div>"
            + f"<div>Expected at: {zip_path}</div>",
            None,
        )
    logs = [f"🐞 Stage(repo zip) at {_now_str()}"]
    _, WORK_DIR, LOG_PATH, ZIP_PATH = _prepare_workspace(logs)
    try:
        shutil.copy2(zip_path, ZIP_PATH)
        logs.append(f"📦 Staged repo output.zip → runs/{WORK_DIR.name}/output.zip")
        _write_logs(LOG_PATH, logs)
    except Exception as e:
        logs.append(f"❌ Failed staging output.zip: {e}")
        _write_logs(LOG_PATH, logs)
        return "<div style='color:#b00'>Failed to stage output.zip</div>"
    return debug_compile_last_pipeline_zip()
    logs = [f"🐞 Debug(real) at {_now_str()}"]
    zip_path = ROOT / "output.zip"
    if not zip_path.exists():
        return (
            "<div style='color:#b00'><b>output.zip not found at repo root.</b></div>"
            + f"<div>Expected at: {zip_path}</div>",
            None,
        )

    # Prepare workspace
    run_id, WORK_DIR, LOG_PATH, _ = _prepare_workspace(logs)
    work_zip_dir = WORK_DIR / "zip_proj"
    work_zip_dir.mkdir(parents=True, exist_ok=True)
    logs.append(f"Workspace: runs/{WORK_DIR.name}")
    logs.append("Unzipping output.zip → zip_proj/")

    # Extract zip
    try:
        import zipfile as _zf
        with _zf.ZipFile(zip_path, 'r') as zf:
            zf.extractall(work_zip_dir)
    except Exception as e:
        logs.append(f"❌ unzip failed: {e}")
        _write_logs(LOG_PATH, logs)
        return "<div style='color:#b00'>Unzip failed.</div>", None

    # Locate poster_output.tex (fallback to poster.tex)
    tex_path = None
    for name in ("poster_output.tex", "poster.tex"):
        cand = list(work_zip_dir.rglob(name))
        if cand:
            tex_path = cand[0]
            break
    if tex_path is None:
        # fallback: any .tex
        cand = list(work_zip_dir.rglob("*.tex"))
        if cand:
            tex_path = cand[0]
    if tex_path is None:
        logs.append("❌ No .tex file found in output.zip")
        _write_logs(LOG_PATH, logs)
        return "<div style='color:#b00'>No .tex found in output.zip</div>", None

    # If left_logo missing, disable \logoleft
    try:
        logos_dir = tex_path.parent / "logos"
        has_left = False
        if logos_dir.exists():
            for p in logos_dir.iterdir():
                if p.is_file() and p.stem == "left_logo":
                    has_left = True
                    break
        if not has_left:
            txt = tex_path.read_text(encoding="utf-8")
            if "\\logoleft" in txt:
                import re as _re
                new_txt = _re.sub(r"^\\\s*logoleft\s*\{.*?\}\s*$", lambda m: "%" + m.group(0), txt, flags=_re.MULTILINE)
                if new_txt != txt:
                    tex_path.write_text(new_txt, encoding="utf-8")
                    logs.append("ℹ️ No left_logo found; disabled \\logoleft in zip project.")
    except Exception as e:
        logs.append(f"⚠️ left_logo adjust failed: {e}")

    # Compile to PDF
    pdf_path = _compile_tex_to_pdf(tex_path, logs)
    if not pdf_path or not pdf_path.exists():
        logs.append("❌ Failed to compile zip PDF.")
        _write_logs(LOG_PATH, logs)
        return (
            "<div style='color:#b00'><b>Compile failed.</b></div>"
            + "<pre style='white-space:pre-wrap;background:#f7f7f8;padding:8px;border-radius:6px'>"
            + "\n".join(logs)
            + "</pre>",
            None,
        )

    try:
        b64 = base64.b64encode(pdf_path.read_bytes()).decode("utf-8")
        open_tab = f"<a target='_blank' rel='noopener' href='data:application/pdf;base64,{b64}'>Open PDF in new tab</a>"
        html = (
            f"<div style='margin-bottom:8px'>{open_tab}</div>"
            + _pdf_to_iframe_html(pdf_path, height="700px")
        )
        _write_logs(LOG_PATH, logs)
        return html, str(pdf_path)
    except Exception as e:
        logs.append(f"⚠️ preview failed: {e}")
        _write_logs(LOG_PATH, logs)
        return f"<div>Compiled but preview failed: {e}</div>", None

def _find_last_pipeline_zip():
    try:
        candidates = []
        for d in RUNS_DIR.iterdir():
            try:
                if d.is_dir():
                    z = d / "output.zip"
                    if z.exists():
                        candidates.append((z.stat().st_mtime, z))
            except Exception:
                pass
        if not candidates:
            return None
        candidates.sort(key=lambda x: x[0], reverse=True)
        return candidates[0][1]
    except Exception:
        return None

def debug_compile_last_pipeline_zip():
    """Find the most recent runs/*/output.zip from pipeline, compile, and return preview HTML + PDF path."""
    logs = [f"🐞 Debug(last-pipeline-zip) at {_now_str()}"]
    last_zip = _find_last_pipeline_zip()
    if not last_zip:
        repo_zip = ROOT / "output.zip"
        if repo_zip.exists():
            try:
                _, W, L, Z = _prepare_workspace(logs)
                shutil.copy2(repo_zip, Z)
                logs.append(f"📦 Auto-staged repo output.zip → runs/{W.name}/output.zip")
                last_zip = Z
            except Exception as e:
                logs.append(f"❌ Auto-stage failed: {e}")
                return "<div style='color:#b00'>No recent pipeline output.zip found and auto-stage failed.</div>"
        else:
            return "<div style='color:#b00'>No recent pipeline output.zip found under runs/.</div>", None

    # Prepare workspace
    run_id, WORK_DIR, LOG_PATH, _ = _prepare_workspace(logs)
    work_zip_dir = WORK_DIR / "zip_last"
    work_zip_dir.mkdir(parents=True, exist_ok=True)
    logs.append(f"Workspace: runs/{WORK_DIR.name}")
    logs.append(f"Using: {last_zip}")

    # Extract zip
    try:
        import zipfile as _zf
        with _zf.ZipFile(last_zip, 'r') as zf:
            zf.extractall(work_zip_dir)
    except Exception as e:
        logs.append(f"❌ unzip failed: {e}")
        _write_logs(LOG_PATH, logs)
        return "<div style='color:#b00'>Unzip failed.</div>", None

    # Locate tex
    tex_path = None
    for name in ("poster_output.tex", "poster.tex"):
        cand = list(work_zip_dir.rglob(name))
        if cand:
            tex_path = cand[0]
            break
    if tex_path is None:
        cand = list(work_zip_dir.rglob("*.tex"))
        if cand:
            tex_path = cand[0]
    if tex_path is None:
        logs.append("❌ No .tex file found in last pipeline zip")
        _write_logs(LOG_PATH, logs)
        return "<div style='color:#b00'>No .tex found in last pipeline zip</div>", None

    # Ensure local fonts and theme precedence (same as other debug path)
    try:
        src_fonts = ROOT / "template" / "fonts"
        dst_fonts = work_zip_dir / "fonts"
        if src_fonts.exists():
            for root_dir, dirs, files in os.walk(src_fonts):
                rel = Path(root_dir).relative_to(src_fonts)
                out_dir = dst_fonts / rel
                out_dir.mkdir(parents=True, exist_ok=True)
                for fn in files:
                    if fn.lower().endswith((".ttf", ".otf")):
                        shutil.copy2(Path(root_dir)/fn, out_dir/fn)
            logs.append("📁 Copied local fonts → zip_last/fonts/")
        # Copy repository theme .sty next to tex and at root
        try:
            tmpl_dir = ROOT / "template"
            for sty in tmpl_dir.glob("*.sty"):
                shutil.copy2(sty, work_zip_dir / sty.name)
                shutil.copy2(sty, tex_path.parent / sty.name)
            logs.append("📄 Copied template/*.sty → zip_last/ and tex dir")
        except Exception as e:
            logs.append(f"⚠️ Copy sty failed: {e}")
    except Exception as e:
        logs.append(f"⚠️ Local font setup failed: {e}")

    # Compile to PDF
    pdf_path = _compile_tex_to_pdf(tex_path, logs)
    if not pdf_path or not pdf_path.exists():
        logs.append("❌ Failed to compile last pipeline zip PDF.")
        _write_logs(LOG_PATH, logs)
        return (
            "<div style='color:#b00'><b>Compile failed.</b></div>"
            + "<pre style='white-space:pre-wrap;background:#f7f7f8;padding:8px;border-radius:6px'>"
            + "\n".join(logs)
            + "</pre>",
            None,
        )
    try:
        b64 = base64.b64encode(pdf_path.read_bytes()).decode("utf-8")
        open_tab = f"<a target='_blank' rel='noopener' href='data:application/pdf;base64,{b64}'>Open PDF in new tab</a>"
        html = (
            f"<div style='margin-bottom:8px'>{open_tab}</div>"
            + _pdf_to_iframe_html(pdf_path, height="700px")
        )
        _write_logs(LOG_PATH, logs)
        return html, str(pdf_path)
    except Exception as e:
        logs.append(f"⚠️ preview failed: {e}")
        _write_logs(LOG_PATH, logs)
        return f"<div>Compiled but preview failed: {e}</div>", None

def debug_compile_uploaded_zip(zip_file):
    """Compile an uploaded poster zip (user-provided); return preview HTML + PDF path."""
    logs = [f"🐞 Debug(upload) at {_now_str()}"]
    if not zip_file:
        return "<div style='color:#b00'>Please upload a .zip file first.</div>", None
    # Prepare workspace
    run_id, WORK_DIR, LOG_PATH, _ = _prepare_workspace(logs)
    work_zip_dir = WORK_DIR / "zip_upload"
    work_zip_dir.mkdir(parents=True, exist_ok=True)
    # Save uploaded zip
    up_path = work_zip_dir / "input.zip"
    try:
        shutil.copy(zip_file.name, up_path)
    except Exception as e:
        logs.append(f"❌ save upload failed: {e}")
        _write_logs(LOG_PATH, logs)
        return "<div style='color:#b00'>Save upload failed.</div>", None
    # Extract
    try:
        import zipfile as _zf
        with _zf.ZipFile(up_path, 'r') as zf:
            zf.extractall(work_zip_dir)
    except Exception as e:
        logs.append(f"❌ unzip failed: {e}")
        _write_logs(LOG_PATH, logs)
        return "<div style='color:#b00'>Unzip failed.</div>", None
    # Find tex
    tex_path = None
    for name in ("poster_output.tex", "poster.tex"):
        cand = list(work_zip_dir.rglob(name))
        if cand:
            tex_path = cand[0]
            break
    if tex_path is None:
        cand = list(work_zip_dir.rglob("*.tex"))
        if cand:
            tex_path = cand[0]
    if tex_path is None:
        logs.append("❌ No .tex file found in uploaded zip")
        _write_logs(LOG_PATH, logs)
        return "<div style='color:#b00'>No .tex found in uploaded zip</div>"
    # Disable logoleft if missing
    try:
        logos_dir = tex_path.parent / "logos"
        has_left = False
        if logos_dir.exists():
            for p in logos_dir.iterdir():
                if p.is_file() and p.stem == "left_logo":
                    has_left = True
                    break
        if not has_left:
            txt = tex_path.read_text(encoding="utf-8")
            if "\\logoleft" in txt:
                import re as _re
                new_txt = _re.sub(r"^\\\s*logoleft\s*\{.*?\}\s*$", lambda m: "%" + m.group(0), txt, flags=_re.MULTILINE)
                if new_txt != txt:
                    tex_path.write_text(new_txt, encoding="utf-8")
                    logs.append("ℹ️ No left_logo found; disabled \\logoleft in uploaded project.")
    except Exception as e:
        logs.append(f"⚠️ left_logo adjust failed: {e}")
    # Compile
    pdf_path = _compile_tex_to_pdf(tex_path, logs)
    if not pdf_path or not pdf_path.exists():
        logs.append("❌ Failed to compile uploaded zip PDF.")
        _write_logs(LOG_PATH, logs)
        return (
            "<div style='color:#b00'><b>Compile failed.</b></div>"
            + "<pre style='white-space:pre-wrap;background:#f7f7f8;padding:8px;border-radius:6px'>"
            + "\n".join(logs)
            + "</pre>",
            None,
        )
    try:
        b64 = base64.b64encode(pdf_path.read_bytes()).decode("utf-8")
        open_tab = f"<a target='_blank' rel='noopener' href='data:application/pdf;base64,{b64}'>Open PDF in new tab</a>"
        html = (
            f"<div style='margin-bottom:8px'>{open_tab}</div>"
            + _pdf_to_iframe_html(pdf_path, height="700px")
        )
        _write_logs(LOG_PATH, logs)
        return "", str(pdf_path)
    except Exception as e:
        logs.append(f"⚠️ preview failed: {e}")
        _write_logs(LOG_PATH, logs)
        return f"<div>Compiled but preview failed: {e}</div>", None

def debug_compile_output_zip():
    """Compile the repo-root output.zip (a real LaTeX project) and preview the resulting PDF."""
    # Stage repo output.zip to runs/<id>/output.zip to follow pipeline layout, then delegate
    zip_path = ROOT / "output.zip"
    if not zip_path.exists():
        return (
            "<div style='color:#b00'><b>output.zip not found at repo root.</b></div>"
            + f"<div>Expected at: {zip_path}</div>",
            None,
        )
    logs = [f"🐞 Stage(repo zip) at {_now_str()}"]
    _, WORK_DIR, LOG_PATH, ZIP_PATH = _prepare_workspace(logs)
    try:
        shutil.copy2(zip_path, ZIP_PATH)
        logs.append(f"📦 Staged repo output.zip → runs/{WORK_DIR.name}/output.zip")
        _write_logs(LOG_PATH, logs)
    except Exception as e:
        logs.append(f"❌ Failed staging output.zip: {e}")
        _write_logs(LOG_PATH, logs)
        return "<div style='color:#b00'>Failed to stage output.zip</div>"
    return debug_compile_last_pipeline_zip()
    logs = [f"🐞 Debug(real) at {_now_str()}"]
    zip_path = ROOT / "output.zip"
    if not zip_path.exists():
        return (
            "<div style='color:#b00'><b>output.zip not found at repo root.</b></div>"
            + f"<div>Expected at: {zip_path}</div>",
            None,
        )

    # Prepare workspace
    run_id, WORK_DIR, LOG_PATH, _ = _prepare_workspace(logs)
    work_zip_dir = WORK_DIR / "zip_proj"
    work_zip_dir.mkdir(parents=True, exist_ok=True)
    logs.append(f"Workspace: runs/{WORK_DIR.name}")
    logs.append("Unzipping output.zip → zip_proj/")

    # Extract zip
    try:
        import zipfile as _zf
        with _zf.ZipFile(zip_path, 'r') as zf:
            zf.extractall(work_zip_dir)
    except Exception as e:
        logs.append(f"❌ unzip failed: {e}")
        _write_logs(LOG_PATH, logs)
        return "<div style='color:#b00'>Unzip failed.</div>", None

    # Locate poster_output.tex (fallback to poster.tex)
    tex_path = None
    for name in ("poster_output.tex", "poster.tex"):
        cand = list(work_zip_dir.rglob(name))
        if cand:
            tex_path = cand[0]
            break
    if tex_path is None:
        # fallback: any .tex
        cand = list(work_zip_dir.rglob("*.tex"))
        if cand:
            tex_path = cand[0]
    if tex_path is None:
        logs.append("❌ No .tex file found in output.zip")
        _write_logs(LOG_PATH, logs)
        return "<div style='color:#b00'>No .tex found in output.zip</div>", None

    # If left_logo missing, disable \logoleft
    try:
        logos_dir = tex_path.parent / "logos"
        has_left = False
        if logos_dir.exists():
            for p in logos_dir.iterdir():
                if p.is_file() and p.stem == "left_logo":
                    has_left = True
                    break
        if not has_left:
            txt = tex_path.read_text(encoding="utf-8")
            if "\\logoleft" in txt:
                import re as _re
                new_txt = _re.sub(r"^\\\s*logoleft\s*\{.*?\}\s*$", lambda m: "%" + m.group(0), txt, flags=_re.MULTILINE)
                if new_txt != txt:
                    tex_path.write_text(new_txt, encoding="utf-8")
                    logs.append("ℹ️ No left_logo found; disabled \\logoleft in zip project.")
    except Exception as e:
        logs.append(f"⚠️ left_logo adjust failed: {e}")

    # Compile to PDF
    pdf_path = _compile_tex_to_pdf(tex_path, logs)
    if not pdf_path or not pdf_path.exists():
        logs.append("❌ Failed to compile zip PDF.")
        _write_logs(LOG_PATH, logs)
        return (
            "<div style='color:#b00'><b>Compile failed.</b></div>"
            + "<pre style='white-space:pre-wrap;background:#f7f7f8;padding:8px;border-radius:6px'>"
            + "\n".join(logs)
            + "</pre>",
            None,
        )

    try:
        b64 = base64.b64encode(pdf_path.read_bytes()).decode("utf-8")
        open_tab = f"<a target='_blank' rel='noopener' href='data:application/pdf;base64,{b64}'>Open PDF in new tab</a>"
        html = (
            f"<div style='margin-bottom:8px'>{open_tab}</div>"
            + _pdf_to_iframe_html(pdf_path, height="700px")
        )
        _write_logs(LOG_PATH, logs)
        return html, str(pdf_path)
    except Exception as e:
        logs.append(f"⚠️ preview failed: {e}")
        _write_logs(LOG_PATH, logs)
        return f"<div>Compiled but preview failed: {e}</div>", None

def _find_last_pipeline_zip():
    try:
        candidates = []
        for d in RUNS_DIR.iterdir():
            try:
                if d.is_dir():
                    z = d / "output.zip"
                    if z.exists():
                        candidates.append((z.stat().st_mtime, z))
            except Exception:
                pass
        if not candidates:
            return None
        candidates.sort(key=lambda x: x[0], reverse=True)
        return candidates[0][1]
    except Exception:
        return None

def debug_compile_last_pipeline_zip():
    """Find the most recent runs/*/output.zip from pipeline, compile, and return preview HTML + PDF path."""
    logs = [f"🐞 Debug(last-pipeline-zip) at {_now_str()}"]
    last_zip = _find_last_pipeline_zip()
    if not last_zip:
        repo_zip = ROOT / "output.zip"
        if repo_zip.exists():
            try:
                _, W, L, Z = _prepare_workspace(logs)
                shutil.copy2(repo_zip, Z)
                logs.append(f"📦 Auto-staged repo output.zip → runs/{W.name}/output.zip")
                last_zip = Z
            except Exception as e:
                logs.append(f"❌ Auto-stage failed: {e}")
                return "<div style='color:#b00'>No recent pipeline output.zip found and auto-stage failed.</div>"
        else:
            return "<div style='color:#b00'>No recent pipeline output.zip found under runs/.</div>", None

    # Prepare workspace
    run_id, WORK_DIR, LOG_PATH, _ = _prepare_workspace(logs)
    work_zip_dir = WORK_DIR / "zip_last"
    work_zip_dir.mkdir(parents=True, exist_ok=True)
    logs.append(f"Workspace: runs/{WORK_DIR.name}")
    logs.append(f"Using: {last_zip}")

    # Extract zip
    try:
        import zipfile as _zf
        with _zf.ZipFile(last_zip, 'r') as zf:
            zf.extractall(work_zip_dir)
    except Exception as e:
        logs.append(f"❌ unzip failed: {e}")
        _write_logs(LOG_PATH, logs)
        return "<div style='color:#b00'>Unzip failed.</div>", None

    # Locate tex
    tex_path = None
    for name in ("poster_output.tex", "poster.tex"):
        cand = list(work_zip_dir.rglob(name))
        if cand:
            tex_path = cand[0]
            break
    if tex_path is None:
        cand = list(work_zip_dir.rglob("*.tex"))
        if cand:
            tex_path = cand[0]
    if tex_path is None:
        logs.append("❌ No .tex file found in last pipeline zip")
        _write_logs(LOG_PATH, logs)
        return "<div style='color:#b00'>No .tex found in last pipeline zip</div>", None

    # Ensure local fonts and theme precedence (same as other debug path)
    try:
        src_fonts = ROOT / "template" / "fonts"
        dst_fonts = work_zip_dir / "fonts"
        if src_fonts.exists():
            for root_dir, dirs, files in os.walk(src_fonts):
                rel = Path(root_dir).relative_to(src_fonts)
                out_dir = dst_fonts / rel
                out_dir.mkdir(parents=True, exist_ok=True)
                for fn in files:
                    if fn.lower().endswith((".ttf", ".otf")):
                        shutil.copy2(Path(root_dir)/fn, out_dir/fn)
            logs.append("📁 Copied local fonts → zip_last/fonts/")
        # Copy repository theme .sty next to tex and at root
        try:
            tmpl_dir = ROOT / "template"
            for sty in tmpl_dir.glob("*.sty"):
                shutil.copy2(sty, work_zip_dir / sty.name)
                shutil.copy2(sty, tex_path.parent / sty.name)
            logs.append("📄 Copied template/*.sty → zip_last/ and tex dir")
        except Exception as e:
            logs.append(f"⚠️ Copy sty failed: {e}")
    except Exception as e:
        logs.append(f"⚠️ Local font setup failed: {e}")

    # Compile to PDF
    pdf_path = _compile_tex_to_pdf(tex_path, logs)
    if not pdf_path or not pdf_path.exists():
        logs.append("❌ Failed to compile last pipeline zip PDF.")
        _write_logs(LOG_PATH, logs)
        return (
            "<div style='color:#b00'><b>Compile failed.</b></div>"
            + "<pre style='white-space:pre-wrap;background:#f7f7f8;padding:8px;border-radius:6px'>"
            + "\n".join(logs)
            + "</pre>",
            None,
        )
    try:
        b64 = base64.b64encode(pdf_path.read_bytes()).decode("utf-8")
        open_tab = f"<a target='_blank' rel='noopener' href='data:application/pdf;base64,{b64}'>Open PDF in new tab</a>"
        html = (
            f"<div style='margin-bottom:8px'>{open_tab}</div>"
            + _pdf_to_iframe_html(pdf_path, height="700px")
        )
        _write_logs(LOG_PATH, logs)
        return html, str(pdf_path)
    except Exception as e:
        logs.append(f"⚠️ preview failed: {e}")
        _write_logs(LOG_PATH, logs)
        return f"<div>Compiled but preview failed: {e}</div>", None

def debug_compile_uploaded_zip(zip_file):
    """Compile an uploaded poster zip (user-provided); return preview HTML + PDF path."""
    logs = [f"🐞 Debug(upload) at {_now_str()}"]
    if not zip_file:
        return "<div style='color:#b00'>Please upload a .zip file first.</div>", None
    # Prepare workspace
    run_id, WORK_DIR, LOG_PATH, _ = _prepare_workspace(logs)
    work_zip_dir = WORK_DIR / "zip_upload"
    work_zip_dir.mkdir(parents=True, exist_ok=True)
    # Save uploaded zip
    up_path = work_zip_dir / "input.zip"
    try:
        shutil.copy(zip_file.name, up_path)
    except Exception as e:
        logs.append(f"❌ save upload failed: {e}")
        _write_logs(LOG_PATH, logs)
        return "<div style='color:#b00'>Save upload failed.</div>", None
    # Extract
    try:
        import zipfile as _zf
        with _zf.ZipFile(up_path, 'r') as zf:
            zf.extractall(work_zip_dir)
    except Exception as e:
        logs.append(f"❌ unzip failed: {e}")
        _write_logs(LOG_PATH, logs)
        return "<div style='color:#b00'>Unzip failed.</div>", None
    # Find tex
    tex_path = None
    for name in ("poster_output.tex", "poster.tex"):
        cand = list(work_zip_dir.rglob(name))
        if cand:
            tex_path = cand[0]
            break
    if tex_path is None:
        cand = list(work_zip_dir.rglob("*.tex"))
        if cand:
            tex_path = cand[0]
    if tex_path is None:
        logs.append("❌ No .tex file found in uploaded zip")
        _write_logs(LOG_PATH, logs)
        return "<div style='color:#b00'>No .tex found in uploaded zip</div>"
    # Disable logoleft if missing
    try:
        logos_dir = tex_path.parent / "logos"
        has_left = False
        if logos_dir.exists():
            for p in logos_dir.iterdir():
                if p.is_file() and p.stem == "left_logo":
                    has_left = True
                    break
        if not has_left:
            txt = tex_path.read_text(encoding="utf-8")
            if "\\logoleft" in txt:
                import re as _re
                new_txt = _re.sub(r"^\\\s*logoleft\s*\{.*?\}\s*$", lambda m: "%" + m.group(0), txt, flags=_re.MULTILINE)
                if new_txt != txt:
                    tex_path.write_text(new_txt, encoding="utf-8")
                    logs.append("ℹ️ No left_logo found; disabled \\logoleft in uploaded project.")
    except Exception as e:
        logs.append(f"⚠️ left_logo adjust failed: {e}")
    # Compile
    pdf_path = _compile_tex_to_pdf(tex_path, logs)
    if not pdf_path or not pdf_path.exists():
        logs.append("❌ Failed to compile uploaded zip PDF.")
        _write_logs(LOG_PATH, logs)
        return (
            "<div style='color:#b00'><b>Compile failed.</b></div>"
            + "<pre style='white-space:pre-wrap;background:#f7f7f8;padding:8px;border-radius:6px'>"
            + "\n".join(logs)
            + "</pre>",
            None,
        )
    try:
        b64 = base64.b64encode(pdf_path.read_bytes()).decode("utf-8")
        open_tab = f"<a target='_blank' rel='noopener' href='data:application/pdf;base64,{b64}'>Open PDF in new tab</a>"
        html = (
            f"<div style='margin-bottom:8px'>{open_tab}</div>"
            + _pdf_to_iframe_html(pdf_path, height="700px")
        )
        _write_logs(LOG_PATH, logs)
        return "", str(pdf_path)
    except Exception as e:
        logs.append(f"⚠️ preview failed: {e}")
        _write_logs(LOG_PATH, logs)
        return f"<div>Compiled but preview failed: {e}</div>", None

def debug_compile_output_zip():
    """Compile the repo-root output.zip (a real LaTeX project) and preview the resulting PDF."""
    # Stage repo output.zip to runs/<id>/output.zip to follow pipeline layout, then delegate
    zip_path = ROOT / "output.zip"
    if not zip_path.exists():
        return (
            "<div style='color:#b00'><b>output.zip not found at repo root.</b></div>"
            + f"<div>Expected at: {zip_path}</div>",
            None,
        )
    logs = [f"🐞 Stage(repo zip) at {_now_str()}"]
    _, WORK_DIR, LOG_PATH, ZIP_PATH = _prepare_workspace(logs)
    try:
        shutil.copy2(zip_path, ZIP_PATH)
        logs.append(f"📦 Staged repo output.zip → runs/{WORK_DIR.name}/output.zip")
        _write_logs(LOG_PATH, logs)
    except Exception as e:
        logs.append(f"❌ Failed staging output.zip: {e}")
        _write_logs(LOG_PATH, logs)
        return "<div style='color:#b00'>Failed to stage output.zip</div>"
    return debug_compile_last_pipeline_zip()
    logs = [f"🐞 Debug(real) at {_now_str()}"]
    zip_path = ROOT / "output.zip"
    if not zip_path.exists():
        return (
            "<div style='color:#b00'><b>output.zip not found at repo root.</b></div>"
            + f"<div>Expected at: {zip_path}</div>"
        )

    # Prepare workspace
    run_id, WORK_DIR, LOG_PATH, _ = _prepare_workspace(logs)
    work_zip_dir = WORK_DIR / "zip_proj"
    work_zip_dir.mkdir(parents=True, exist_ok=True)
    logs.append(f"Workspace: runs/{WORK_DIR.name}")
    logs.append("Unzipping output.zip → zip_proj/")

    # Extract zip
    try:
        import zipfile as _zf
        with _zf.ZipFile(zip_path, 'r') as zf:
            zf.extractall(work_zip_dir)
    except Exception as e:
        logs.append(f"❌ unzip failed: {e}")
        _write_logs(LOG_PATH, logs)
        return "<div style='color:#b00'>Unzip failed.</div>", None

    # Locate poster_output.tex (fallback to poster.tex)
    tex_path = None
    for name in ("poster_output.tex", "poster.tex"):
        cand = list(work_zip_dir.rglob(name))
        if cand:
            tex_path = cand[0]
            break
    if tex_path is None:
        # fallback: any .tex
        cand = list(work_zip_dir.rglob("*.tex"))
        if cand:
            tex_path = cand[0]
    if tex_path is None:
        logs.append("❌ No .tex file found in output.zip")
        _write_logs(LOG_PATH, logs)
        return "<div style='color:#b00'>No .tex found in output.zip</div>", None

    # If left_logo missing, disable \logoleft
    try:
        logos_dir = tex_path.parent / "logos"
        has_left = False
        if logos_dir.exists():
            for p in logos_dir.iterdir():
                if p.is_file() and p.stem == "left_logo":
                    has_left = True
                    break
        if not has_left:
            txt = tex_path.read_text(encoding="utf-8")
            if "\\logoleft" in txt:
                import re as _re
                new_txt = _re.sub(r"^\\\s*logoleft\s*\{.*?\}\s*$", lambda m: "%" + m.group(0), txt, flags=_re.MULTILINE)
                if new_txt != txt:
                    tex_path.write_text(new_txt, encoding="utf-8")
                    logs.append("ℹ️ No left_logo found; disabled \\logoleft in zip project.")
    except Exception as e:
        logs.append(f"⚠️ left_logo adjust failed: {e}")

    # Compile to PDF
    pdf_path = _compile_tex_to_pdf(tex_path, logs)
    if not pdf_path or not pdf_path.exists():
        logs.append("❌ Failed to compile zip PDF.")
        _write_logs(LOG_PATH, logs)
        return (
            "<div style='color:#b00'><b>Compile failed.</b></div>"
            + "<pre style='white-space:pre-wrap;background:#f7f7f8;padding:8px;border-radius:6px'>"
            + "\n".join(logs)
            + "</pre>",
            None,
        )

    try:
        b64 = base64.b64encode(pdf_path.read_bytes()).decode("utf-8")
        open_tab = f"<a target='_blank' rel='noopener' href='data:application/pdf;base64,{b64}'>Open PDF in new tab</a>"
        html = (
            f"<div style='margin-bottom:8px'>{open_tab}</div>"
            + _pdf_to_iframe_html(pdf_path, height="700px")
        )
        _write_logs(LOG_PATH, logs)
        return html, str(pdf_path)
    except Exception as e:
        logs.append(f"⚠️ preview failed: {e}")
        _write_logs(LOG_PATH, logs)
        return f"<div>Compiled but preview failed: {e}</div>", None

def _find_last_pipeline_zip():
    try:
        candidates = []
        for d in RUNS_DIR.iterdir():
            try:
                if d.is_dir():
                    z = d / "output.zip"
                    if z.exists():
                        candidates.append((z.stat().st_mtime, z))
            except Exception:
                pass
        if not candidates:
            return None
        candidates.sort(key=lambda x: x[0], reverse=True)
        return candidates[0][1]
    except Exception:
        return None

def debug_compile_last_pipeline_zip():
    """Find the most recent runs/*/output.zip from pipeline, compile, and return preview HTML + PDF path."""
    logs = [f"🐞 Debug(last-pipeline-zip) at {_now_str()}"]
    last_zip = _find_last_pipeline_zip()
    if not last_zip:
        repo_zip = ROOT / "output.zip"
        if repo_zip.exists():
            try:
                _, W, L, Z = _prepare_workspace(logs)
                shutil.copy2(repo_zip, Z)
                logs.append(f"📦 Auto-staged repo output.zip → runs/{W.name}/output.zip")
                last_zip = Z
            except Exception as e:
                logs.append(f"❌ Auto-stage failed: {e}")
                return "<div style='color:#b00'>No recent pipeline output.zip found and auto-stage failed.</div>"
        else:
            return "<div style='color:#b00'>No recent pipeline output.zip found under runs/.</div>", None

    # Prepare workspace
    run_id, WORK_DIR, LOG_PATH, _ = _prepare_workspace(logs)
    work_zip_dir = WORK_DIR / "zip_last"
    work_zip_dir.mkdir(parents=True, exist_ok=True)
    logs.append(f"Workspace: runs/{WORK_DIR.name}")
    logs.append(f"Using: {last_zip}")

    # Extract zip
    try:
        import zipfile as _zf
        with _zf.ZipFile(last_zip, 'r') as zf:
            zf.extractall(work_zip_dir)
    except Exception as e:
        logs.append(f"❌ unzip failed: {e}")
        _write_logs(LOG_PATH, logs)
        return "<div style='color:#b00'>Unzip failed.</div>", None

    # Locate tex
    tex_path = None
    for name in ("poster_output.tex", "poster.tex"):
        cand = list(work_zip_dir.rglob(name))
        if cand:
            tex_path = cand[0]
            break
    if tex_path is None:
        cand = list(work_zip_dir.rglob("*.tex"))
        if cand:
            tex_path = cand[0]
    if tex_path is None:
        logs.append("❌ No .tex file found in last pipeline zip")
        _write_logs(LOG_PATH, logs)
        return "<div style='color:#b00'>No .tex found in last pipeline zip</div>", None

    # Ensure local fonts and theme precedence (same as other debug path)
    try:
        src_fonts = ROOT / "template" / "fonts"
        dst_fonts = work_zip_dir / "fonts"
        if src_fonts.exists():
            for root_dir, dirs, files in os.walk(src_fonts):
                rel = Path(root_dir).relative_to(src_fonts)
                out_dir = dst_fonts / rel
                out_dir.mkdir(parents=True, exist_ok=True)
                for fn in files:
                    if fn.lower().endswith((".ttf", ".otf")):
                        shutil.copy2(Path(root_dir)/fn, out_dir/fn)
            logs.append("📁 Copied local fonts → zip_last/fonts/")
        # Copy repository theme .sty next to tex and at root
        try:
            tmpl_dir = ROOT / "template"
            for sty in tmpl_dir.glob("*.sty"):
                shutil.copy2(sty, work_zip_dir / sty.name)
                shutil.copy2(sty, tex_path.parent / sty.name)
            logs.append("📄 Copied template/*.sty → zip_last/ and tex dir")
        except Exception as e:
            logs.append(f"⚠️ Copy sty failed: {e}")
    except Exception as e:
        logs.append(f"⚠️ Local font setup failed: {e}")

    # Compile to PDF
    pdf_path = _compile_tex_to_pdf(tex_path, logs)
    if not pdf_path or not pdf_path.exists():
        logs.append("❌ Failed to compile last pipeline zip PDF.")
        _write_logs(LOG_PATH, logs)
        return (
            "<div style='color:#b00'><b>Compile failed.</b></div>"
            + "<pre style='white-space:pre-wrap;background:#f7f7f8;padding:8px;border-radius:6px'>"
            + "\n".join(logs)
            + "</pre>",
            None,
        )
    try:
        b64 = base64.b64encode(pdf_path.read_bytes()).decode("utf-8")
        open_tab = f"<a target='_blank' rel='noopener' href='data:application/pdf;base64,{b64}'>Open PDF in new tab</a>"
        html = (
            f"<div style='margin-bottom:8px'>{open_tab}</div>"
            + _pdf_to_iframe_html(pdf_path, height="700px")
        )
        _write_logs(LOG_PATH, logs)
        return html, str(pdf_path)
    except Exception as e:
        logs.append(f"⚠️ preview failed: {e}")
        _write_logs(LOG_PATH, logs)
        return f"<div>Compiled but preview failed: {e}</div>", None

def debug_compile_uploaded_zip(zip_file):
    """Compile an uploaded poster zip (user-provided); return preview HTML + PDF path."""
    logs = [f"🐞 Debug(upload) at {_now_str()}"]
    if not zip_file:
        return "<div style='color:#b00'>Please upload a .zip file first.</div>", None
    # Prepare workspace
    run_id, WORK_DIR, LOG_PATH, _ = _prepare_workspace(logs)
    work_zip_dir = WORK_DIR / "zip_upload"
    work_zip_dir.mkdir(parents=True, exist_ok=True)
    # Save uploaded zip
    up_path = work_zip_dir / "input.zip"
    try:
        shutil.copy(zip_file.name, up_path)
    except Exception as e:
        logs.append(f"❌ save upload failed: {e}")
        _write_logs(LOG_PATH, logs)
        return "<div style='color:#b00'>Save upload failed.</div>", None
    # Extract
    try:
        import zipfile as _zf
        with _zf.ZipFile(up_path, 'r') as zf:
            zf.extractall(work_zip_dir)
    except Exception as e:
        logs.append(f"❌ unzip failed: {e}")
        _write_logs(LOG_PATH, logs)
        return "<div style='color:#b00'>Unzip failed.</div>", None
    # Find tex
    tex_path = None
    for name in ("poster_output.tex", "poster.tex"):
        cand = list(work_zip_dir.rglob(name))
        if cand:
            tex_path = cand[0]
            break
    if tex_path is None:
        cand = list(work_zip_dir.rglob("*.tex"))
        if cand:
            tex_path = cand[0]
    if tex_path is None:
        logs.append("❌ No .tex file found in uploaded zip")
        _write_logs(LOG_PATH, logs)
        return "<div style='color:#b00'>No .tex found in uploaded zip</div>"
    # Disable logoleft if missing
    try:
        logos_dir = tex_path.parent / "logos"
        has_left = False
        if logos_dir.exists():
            for p in logos_dir.iterdir():
                if p.is_file() and p.stem == "left_logo":
                    has_left = True
                    break
        if not has_left:
            txt = tex_path.read_text(encoding="utf-8")
            if "\\logoleft" in txt:
                import re as _re
                new_txt = _re.sub(r"^\\\s*logoleft\s*\{.*?\}\s*$", lambda m: "%" + m.group(0), txt, flags=_re.MULTILINE)
                if new_txt != txt:
                    tex_path.write_text(new_txt, encoding="utf-8")
                    logs.append("ℹ️ No left_logo found; disabled \\logoleft in uploaded project.")
    except Exception as e:
        logs.append(f"⚠️ left_logo adjust failed: {e}")
    # Compile
    pdf_path = _compile_tex_to_pdf(tex_path, logs)
    if not pdf_path or not pdf_path.exists():
        logs.append("❌ Failed to compile uploaded zip PDF.")
        _write_logs(LOG_PATH, logs)
        return (
            "<div style='color:#b00'><b>Compile failed.</b></div>"
            + "<pre style='white-space:pre-wrap;background:#f7f7f8;padding:8px;border-radius:6px'>"
            + "\n".join(logs)
            + "</pre>",
            None,
        )
    try:
        b64 = base64.b64encode(pdf_path.read_bytes()).decode("utf-8")
        open_tab = f"<a target='_blank' rel='noopener' href='data:application/pdf;base64,{b64}'>Open PDF in new tab</a>"
        html = (
            f"<div style='margin-bottom:8px'>{open_tab}</div>"
            + _pdf_to_iframe_html(pdf_path, height="700px")
        )
        _write_logs(LOG_PATH, logs)
        return "", str(pdf_path)
    except Exception as e:
        logs.append(f"⚠️ preview failed: {e}")
        _write_logs(LOG_PATH, logs)
        return f"<div>Compiled but preview failed: {e}</div>", None

# =====================
# Gradio pipeline function (ISOLATED)
# =====================
def run_pipeline(
    arxiv_url,
    pdf_file,
    openai_key,
    logo_files,
    meeting_logo_file,
    theme_rgb,
    openai_base_url="",
    model_name_t="",
    model_name_v="",
):
    try:
        openai_base_url, model_name_t, model_name_v = resolve_openai_settings(
            openai_base_url, model_name_t, model_name_v
        )
    except ValueError as error:
        yield f"❌ OpenAI endpoint settings: {error}", "", None, None, ""
        return

    _cleanup_old_runs(RETENTION_HOURS)

    start_time = datetime.datetime.now()
    logs = [f"🚀 Starting pipeline at {_now_str()}"]

    # --- Prepare per-run workspace ---
    run_id, WORK_DIR, LOG_PATH, ZIP_PATH = _prepare_workspace(logs)
    INPUT_DIR = WORK_DIR / "input"
    OUTPUT_DIR = WORK_DIR / "output"
    LOGO_DIR = INPUT_DIR / "logo"
    POSTER_LATEX_DIR = WORK_DIR / "posterbuilder" / "latex_proj"

    _write_logs(LOG_PATH, logs)
    yield "\n".join(logs), "", None, None, ""

    # ====== Validation: must upload LOGO ======
    if logo_files is None:
        logo_files = []
    if not isinstance(logo_files, (list, tuple)):
        logo_files = [logo_files]
    logo_files = [f for f in logo_files if f]

    # if len(logo_files) == 0:
    #     msg = "❌ You must upload at least one institutional logo (multiple allowed)."
    #     logs.append(msg)
    #     _write_logs(LOG_PATH, logs)
    #     yield "\n".join(logs), "", None, ""
    #     return

    # Save logos into run-local dir
    for item in LOGO_DIR.iterdir():
        if item.is_file():
            item.unlink()
    saved_logo_paths = []
    for lf in logo_files:
        p = LOGO_DIR / Path(lf.name).name
        shutil.copy(lf.name, p)
        saved_logo_paths.append(p)
    logs.append(f"🏷️ Saved {len(saved_logo_paths)} logo file(s) → {LOGO_DIR.relative_to(WORK_DIR)}")
    _write_logs(LOG_PATH, logs)
    yield "\n".join(logs), "", None, None, ""

    # ====== Handle uploaded PDF (optional) ======
    pdf_path = None
    if pdf_file:
        pdf_dir = INPUT_DIR / "pdf"
        pdf_dir.mkdir(parents=True, exist_ok=True)
        pdf_path = pdf_dir / Path(pdf_file.name).name
        shutil.copy(pdf_file.name, pdf_path)
        logs.append(f"📄 Uploaded PDF → {pdf_path.relative_to(WORK_DIR)}")

        # For pipeline Step 1.5 compatibility: also copy to input/paper.pdf
        canonical_pdf = INPUT_DIR / "paper.pdf"
        shutil.copy(pdf_file.name, canonical_pdf)
        _write_logs(LOG_PATH, logs)
        yield "\n".join(logs), "", None, None, ""

    # ====== Validate input source ======
    if not arxiv_url and not pdf_file:
        msg = "❌ Please provide either an arXiv link or upload a PDF file (choose one)."
        logs.append(msg)
        _write_logs(LOG_PATH, logs)
        yield "\n".join(logs), "", None, None, ""
        return

    # ====== Build command (run INSIDE workspace) ======
    cmd = [
        sys.executable, "pipeline.py",
        "--model_name_t", model_name_t,
        "--model_name_v", model_name_v,
        "--openai_base_url", openai_base_url,
        "--result_dir", "output",
        "--paper_latex_root", "input/latex_proj",
        "--openai_key", openai_key,
        "--gemini_key", "##",
        "--logo_dir", str(LOGO_DIR)  # run-local logo dir
    ]
    if arxiv_url:
        cmd += ["--arxiv_url", arxiv_url]
    # (Keep pdf via input/paper.pdf; pipeline will read it if exists)

    logs.append("\n======= REAL-TIME LOG =======")
    logs.append(f"cwd = runs/{WORK_DIR.name}")
    _write_logs(LOG_PATH, logs)
    yield "\n".join(logs), "", None, None, ""

    # ====== Run with REAL-TIME streaming, inside workspace ======
    try:
        process = subprocess.Popen(
            cmd,
            cwd=str(WORK_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            universal_newlines=True,
        )
    except Exception as e:
        msg = f"❌ Pipeline failed to start: {e}"
        logs.append(msg)
        _write_logs(LOG_PATH, logs)
        yield "\n".join(logs), "", None, None, ""
        return

    last_yield = time.time()
    try:
        while True:
            # Timeout guard
            if (datetime.datetime.now() - start_time).total_seconds() > TIMEOUT_SECONDS:
                logs.append("❌ Pipeline timed out (30 min limit). Killing process…")
                try:
                    process.kill()
                except Exception:
                    pass
                _write_logs(LOG_PATH, logs)
                yield "\n".join(logs), "", None, None, ""
                return

            line = process.stdout.readline()
            if line:
                print(line, end="")  # echo to Space logs
                logs.append(line.rstrip("\n"))
                _write_logs(LOG_PATH, logs)
                now = time.time()
                if now - last_yield >= 0.3:
                    last_yield = now
                    yield "\n".join(logs), "", None, None, ""
            elif process.poll() is not None:
                break
            else:
                time.sleep(0.05)

        return_code = process.wait()
        logs.append(f"\nProcess finished with code {return_code}")
        _write_logs(LOG_PATH, logs)
        yield "\n".join(logs), "", None, None, ""

        if return_code != 0:
            logs.append("❌ Process exited with non-zero status. See logs above.")
            _write_logs(LOG_PATH, logs)
            yield "\n".join(logs), "", None, None, ""
            return

    except Exception as e:
        logs.append(f"❌ Error during streaming: {e}")
        _write_logs(LOG_PATH, logs)
        yield "\n".join(logs), "", None, None, ""
        return
    finally:
        try:
            if process.stdout:
                process.stdout.close()
        except Exception:
            pass

    # ====== Check output ======
    has_output = False
    try:
        if OUTPUT_DIR.exists():
            for _ in OUTPUT_DIR.iterdir():
                has_output = True
                break
    except FileNotFoundError:
        has_output = False

    if not has_output:
        msg = "❌ No output generated. Please check logs above."
        logs.append(msg)
        _write_logs(LOG_PATH, logs)
        yield "\n".join(logs), "", None, None, ""
        return

    # ====== NEW: Post-processing (optional features) ======
    # 1) Optional meeting logo replacement; if not provided, apply default NeurIPS
    applied_logo = _apply_meeting_logo(OUTPUT_DIR, meeting_logo_file, logs)
    if not applied_logo:
        _ensure_right_logo_default(OUTPUT_DIR, logs)

    # 2) Optional theme color update
    rgb_tuple = _parse_rgb(theme_rgb)
    if theme_rgb and not rgb_tuple:
        logs.append(f"⚠️ Ignored Theme RGB input '{theme_rgb}': expected like '94,46,145'.")
    applied_rgb = _apply_theme_rgb(OUTPUT_DIR, rgb_tuple, logs) if rgb_tuple else False

    # 3) Optional institutional logo -> left_logo.<ext>
    _apply_left_logo(OUTPUT_DIR, logo_files, logs)
    _ensure_left_logo_or_disable(OUTPUT_DIR, logs)

    _write_logs(LOG_PATH, logs)
    yield "\n".join(logs), "", None, None, ""


    _write_logs(LOG_PATH, logs)
    yield "\n".join(logs), "", None, None, ""

    # ====== Compile PDF (for download + image preview) ======
    pdf_html = ""
    compiled_pdf_file = None
    try:
        pdf_path = _compile_poster_pdf(OUTPUT_DIR, logs)
        if pdf_path and pdf_path.exists():
            # Prefer file-served iframe to avoid large data: URIs and browser blocks
            pdf_html = _pdf_to_iframe_file(pdf_path)
            compiled_pdf_file = str(pdf_path)
            logs.append("🖨️ PDF compiled (image preview available).")
    except Exception as e:
        logs.append(f"⚠️ PDF compile skipped: {e}")

    # ====== Zip output (run-local) ======
    try:
        target_dir = OUTPUT_DIR / "poster_latex_proj"

        if not target_dir.exists():
            logs.append("❌ poster_latex_proj folder not found")
        else:
            with zipfile.ZipFile(ZIP_PATH, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for root, dirs, files in os.walk(target_dir):
                    for file in files:
                        file_path = Path(root) / file
                        arcname = file_path.relative_to(target_dir)  # only relative to subfolder
                        zipf.write(file_path, arcname=arcname)

            logs.append(f"✅ Zipped poster_latex_proj → {ZIP_PATH.relative_to(WORK_DIR)}")

    except Exception as e:
        logs.append(f"❌ Failed to create zip: {e}")

    # ====== Prepare Overleaf base64 payload (optional) ======
    overleaf_zip_b64 = ""
    try:
        with open(ZIP_PATH, "rb") as f:
            overleaf_zip_b64 = base64.b64encode(f.read()).decode("utf-8")
        logs.append("🔗 Prepared Overleaf base64 payload")
    except Exception as e:
        logs.append(f"⚠️ Failed Overleaf payload: {e}")

    end_time = datetime.datetime.now()
    dur = (end_time - start_time).seconds
    logs.append(f"🏁 Completed at {_now_str()} (Duration: {dur}s)")
    logs.append(f"🆔 run_id = {WORK_DIR.name}")

    _write_logs(LOG_PATH, logs)
    yield "\n".join(logs), (
        pdf_html
    ), (
        compiled_pdf_file
    ), (
        str(ZIP_PATH) if ZIP_PATH.exists() else None
    ), render_overleaf_button(overleaf_zip_b64)


def debug_compile():
    # Minimal debug disabled to simplify UI.
    return "<div style='color:#555'>Minimal debug disabled. Use 'Test repo output.zip' or 'Test last pipeline zip'.</div>"


# =====================
# Gradio UI
# =====================
with gr.Blocks(title="🎓 Paper2Poster") as iface:
    # Title
    gr.Markdown("# 🎓 Paper2Poster")
    gr.Markdown("""
[Paper](https://arxiv.org/abs/2505.21497) | [GitHub](https://github.com/Paper2Poster/Paper2Poster) | [Project Page](https://paper2poster.github.io/)  

**TL;DR:** Upload your paper and get an auto-generated poster.
Please be patient — each paper takes about 8–10 minutes to process.

This work, developed in collaboration with [TVG@Oxford](https://torrvision.com/index.html) and [UWaterloo](https://uwaterloo.ca/), has been accepted to [NeurIPS 2025 D&B](https://neurips.cc/). The framework builds upon 🐪 [CAMEL-ai](https://github.com/camel-ai/camel).
""", elem_id="intro-md")
    # Top-right logos (camel, tvg, waterloo) if available
    gr.HTML(_ui_header_logos_html())

    # Note: CAMEL line merged into the Markdown above to keep it on the same line.

    # -------- Input box --------
    with gr.Row():
        # ========== LEFT: INPUT ==========
        with gr.Column(scale=1):
            with gr.Accordion("Input", open=True):
                arxiv_in = gr.Textbox(label="📘 ArXiv URL (choose one)", placeholder="https://arxiv.org/abs/2505.xxxxx")
                pdf_in   = gr.File(label="📄 Upload PDF (choose one)")
                key_in   = gr.Textbox(label="🔑 OpenAI API Key", placeholder="sk-...", type="password")
                openai_base_url_in = gr.Textbox(
                    label="OpenAI-compatible API base URL (optional)",
                    placeholder="https://host.example/v1",
                    info="Leave blank to use OpenAI's default endpoint.",
                )
                model_name_t_in = gr.Textbox(
                    label="Text model ID (custom endpoints)",
                    placeholder="For example: gpt-5",
                    info="Required when a custom API base URL is set.",
                )
                model_name_v_in = gr.Textbox(
                    label="Vision model ID (custom endpoints)",
                    placeholder="For example: gpt-5",
                    info="Required when a custom API base URL is set; the model must accept image input.",
                )

                inst_logo_in = gr.File(
                    label="🏷️ Institutional Logo (optional, multiple allowed)",
                    file_count="multiple",
                    file_types=["image"],
                )

                with gr.Row():
                    with gr.Column():
                        conf_logo_in = gr.File(
                            label="🧩 Optional: Conference Logo (defaults to NeurIPS logo)",
                            file_count="single",
                            file_types=["image"],
                        )
                    with gr.Column():
                        _conf_path = _default_conf_logo_path()
                        conf_preview = gr.Image(
                            value=str(_conf_path) if _conf_path else None,
                            label="Default conference logo preview",
                            interactive=False,
                        )

                theme_in = gr.ColorPicker(label="🎨 Theme Color (optional)", value="#5E2E91")
                run_btn = gr.Button("🚀 Run", variant="primary")

        # ========== RIGHT: OUTPUT ==========
        with gr.Column(scale=1):
            with gr.Accordion("Output", open=True):
                # Preview on top
                img_out      = gr.Image(label="🖼️ Poster (Image Preview)", interactive=False)
                # Logs in the middle (keep compact height)
                logs_out     = gr.Textbox(label="🧾 Logs", lines=10, max_lines=20)
                # Downloads at bottom
                pdf_out      = gr.HTML(label="📄 Poster (PDF Preview)", visible=False)
                with gr.Row():
                    pdf_file_out = gr.File(label="📄 Download Poster (PDF)", interactive=False, visible=True)
                    zip_out      = gr.File(label="📦 Download Results (.zip)", interactive=False, visible=True)
                gr.Markdown("The ZIP can be uploaded to Overleaf and compiled with XeLaTeX.")
                overleaf_out = gr.HTML(label="Open in Overleaf")
                # Debug (hidden)
                debug_zip_btn= gr.Button("🐞 Test repo output.zip", variant="secondary", visible=False)
                debug_zip_out= gr.HTML(label="🐞 Real Output Preview", visible=False)
                debug_zip_img= gr.Image(label="🐞 Real Output Image", interactive=False, visible=False)
                debug_zip_pdfpath = gr.Textbox(visible=False)
                debug_last_btn= gr.Button("🐞 Test last pipeline zip", variant="secondary", visible=False)
                debug_last_out= gr.HTML(label="🐞 Last Pipeline Preview", visible=False)
                debug_last_img= gr.Image(label="🐞 Last Output Image", interactive=False, visible=False)
                debug_last_pdfpath = gr.Textbox(visible=False)

    _run_evt = run_btn.click(
        fn=run_pipeline,
        inputs=[
            arxiv_in,
            pdf_in,
            key_in,
            inst_logo_in,
            conf_logo_in,
            theme_in,
            openai_base_url_in,
            model_name_t_in,
            model_name_v_in,
        ],
        outputs=[logs_out, pdf_out, pdf_file_out, zip_out, overleaf_out],
    )
    _run_evt.then(fn=preview_image_from_pdf, inputs=[pdf_file_out], outputs=[img_out])
    _dz = debug_zip_btn.click(fn=debug_compile_output_zip, inputs=[], outputs=[debug_zip_out, debug_zip_pdfpath])
    _dz.then(fn=preview_image_from_pdf, inputs=[debug_zip_pdfpath], outputs=[debug_zip_img])
    _dl = debug_last_btn.click(fn=debug_compile_last_pipeline_zip, inputs=[], outputs=[debug_last_out, debug_last_pdfpath])
    _dl.then(fn=preview_image_from_pdf, inputs=[debug_last_pdfpath], outputs=[debug_last_img])

if __name__ == "__main__":
    iface.launch(server_name="0.0.0.0", server_port=7860)
