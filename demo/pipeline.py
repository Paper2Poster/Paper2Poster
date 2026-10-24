import time
import shutil
import os, sys
import argparse
import subprocess
from os import path
from pdf2image import convert_from_path
from pathlib import Path
from PIL import Image
from openai_settings import resolve_openai_settings

print("Initializing...")

# from Paper2Video.src.slide_code_gen import latex_code_gen
# from Paper2Video.src.wei_utils import get_agent_config
from posterbuilder import build_poster as build_poster
from posterbuilder.build_poster import IMAGES_DIR_NAME

ROOT_DIR = Path(__file__).resolve().parent
P2V_ASSETS = ROOT_DIR / "Paper2Video" / "assets" / "demo" / "latex_proj"
P2P_ROOT   = ROOT_DIR / "Paper2Poster"
PB_ROOT    = ROOT_DIR / "posterbuilder"
sys.path.append(str(P2P_ROOT))

def copy_folder(src_dir, dst_dir):
    src_dir = Path(src_dir)
    dst_dir = Path(dst_dir)
    if not src_dir.exists():
        raise FileNotFoundError(f"no such dir: {src_dir}")
    if dst_dir.exists():
        shutil.rmtree(dst_dir)
    shutil.copytree(src_dir, dst_dir)
    print(f"✅ Copied folder {src_dir} → {dst_dir}")

def copytree_overwrite(src: Path, dst: Path):
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)

def safe_copy(src: Path, dst: Path):
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)

def str2list(s): 
    return [int(x) for x in s.split(',')]

def run_paper2poster_content_build():
    print("🧩 Step 1.5: Preparing Paper2Poster inputs & generating poster contents ...")

    src_pdf = ROOT_DIR / "input" / "paper.pdf"
    dst_pdf = P2P_ROOT / "input" / "paper" / "paper.pdf"
    dst_pdf.parent.mkdir(parents=True, exist_ok=True)
    safe_copy(src_pdf, dst_pdf)
    cmd = [
        sys.executable, "-m", "PosterAgent.new_pipeline",
        f'--poster_path={dst_pdf.relative_to(P2P_ROOT)}',
        '--model_name_t=gpt-5',
        '--model_name_v=gpt-5',
        '--poster_width_inches=48',
        '--poster_height_inches=36'
    ]
    print("   ▶ Running: python -m PosterAgent.new_pipeline ...")
    subprocess.run(cmd, cwd=str(P2P_ROOT), check=True)
    print("   ✅ PosterAgent.new_pipeline finished.")

    tag_prefix = IMAGES_DIR_NAME.split("_images_and_tables")[0]
    src_raw_content = P2P_ROOT / "contents" / f"{tag_prefix}_paper_raw_content.json"
    src_tree_split  = P2P_ROOT / "tree_splits" / f"{tag_prefix}_paper_tree_split_0.json"
    src_images_json = P2P_ROOT / IMAGES_DIR_NAME / "paper_images.json"

    dst_contents_dir = PB_ROOT / "contents"
    dst_raw_content  = dst_contents_dir / "poster_content.json"
    dst_tree_split   = dst_contents_dir / "arrangement.json"
    dst_fig_caption  = dst_contents_dir / "figure_caption.json"

    dst_root_raw     = PB_ROOT / "poster_content.json"
    dst_root_tree    = PB_ROOT / "arrangement.json"
    dst_root_figcap  = PB_ROOT / "figure_caption.json"

    safe_copy(src_raw_content, dst_raw_content)
    safe_copy(src_tree_split,  dst_tree_split)
    safe_copy(src_images_json, dst_fig_caption)
    safe_copy(src_raw_content, dst_root_raw)
    safe_copy(src_tree_split,  dst_root_tree)
    safe_copy(src_images_json, dst_root_figcap)

    print("   📦 JSON copied & renamed.")
    print("   ✅ Step 1.5 done.\n")

def _list_logo_files(logo_dir: Path):
    exts = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
    files = []
    if logo_dir.exists():
        for p in sorted(logo_dir.iterdir()):
            if p.suffix.lower() in exts and p.is_file():
                files.append(p)
    return files

def _compose_logos_horizontally(logo_paths, out_path: Path, box_w=2000, box_h=476, gap=16):
    """
    宽度为硬约束：输出图像宽度必为 box_w（默认 2000px）。
    多 logo 按比例统一缩放，拼接后刚好占满 box_w（包含间距）。
    高度由比例自然决定，可能 < box_h，也可能 > box_h（甚至 > 2*box_h），不会再二次压缩。
    透明背景，输出 PNG。
    """
    # 读取图片
    imgs = []
    for p in logo_paths:
        p = Path(p)
        if p.exists() and p.is_file():
            imgs.append(Image.open(p).convert("RGBA"))
    n = len(imgs)
    if n == 0:
        raise RuntimeError("No logo images found.")

    # 原始总宽度（不含 gap）；拼接总宽 = sum(w_i) + gap*(n-1)
    widths  = [im.width for im in imgs]
    heights = [im.height for im in imgs]
    sum_w   = sum(widths)
    if sum_w <= 0:
        raise RuntimeError("All logo images have zero width.")

    # 计算统一缩放比例，使：sum(w_i * s) + gap*(n-1) == box_w
    # => s = (box_w - gap*(n-1)) / sum_w
    total_gap = max(0, gap * (n - 1))
    if box_w <= total_gap:
        raise ValueError(f"box_w({box_w}) too small vs total gaps({total_gap}). Increase box_w or reduce gap.")
    s = (box_w - total_gap) / float(sum_w)

    # 按统一比例缩放（四舍五入到整数像素，避免累计误差）
    resized = []
    scaled_widths = []
    scaled_heights = []
    for im, w, h in zip(imgs, widths, heights):
        nw = max(1, int(round(w * s)))
        nh = max(1, int(round(h * s)))
        resized.append(im.resize((nw, nh), Image.LANCZOS))
        scaled_widths.append(nw)
        scaled_heights.append(nh)

    # 由于整数取整，可能出现总宽 !=  box_w - total_gap；对若干图微调 1px 以精确对齐
    current_sum_w = sum(scaled_widths)
    diff = (box_w - total_gap) - current_sum_w
    # 按从宽到窄/从大到小顺序均匀分配像素误差
    if diff != 0:
        order = sorted(range(n), key=lambda i: scaled_widths[i], reverse=(diff > 0))
        idx = 0
        step = 1 if diff > 0 else -1
        remaining = abs(diff)
        while remaining > 0 and n > 0:
            i = order[idx % n]
            new_w = scaled_widths[i] + step
            if new_w >= 1:
                scaled_widths[i] = new_w
                resized[i] = resized[i].resize((new_w, resized[i].height), Image.LANCZOS)
                remaining -= 1
            idx += 1

    # 计算最终尺寸
    total_w = sum(scaled_widths) + total_gap
    assert total_w == box_w, f"width pack mismatch: got {total_w}, expect {box_w}"
    canvas_w = box_w
    canvas_h = max(im.height for im in resized)  # 高度由比例自然决定（可能 > 2*box_h）

    # 画布 & 居中摆放（垂直方向居中）
    canvas = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
    cur_x = 0
    for idx, im in enumerate(resized):
        y = (canvas_h - im.height) // 2
        canvas.alpha_composite(im, (cur_x, y))
        cur_x += im.width
        if idx != n - 1:
            cur_x += gap

    # out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out_path, format="PNG")
    print(f"   🧩 Logos composed (width-locked) → {out_path.relative_to(ROOT_DIR)} "
          f"(n={n}, final_size={canvas_w}x{canvas_h})")




if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Paper2Video Generation Pipeline')
    parser.add_argument('--result_dir', type=str, default='output')
    parser.add_argument('--model_name_t', type=str, default='')
    parser.add_argument('--model_name_v', type=str, default='')
    parser.add_argument('--openai_base_url', type=str, default='')
    parser.add_argument('--paper_latex_root', type=str, default=str(P2V_ASSETS))
    parser.add_argument('--ref_text', type=str, default=None)
    parser.add_argument('--if_tree_search', type=bool, default=True)
    parser.add_argument('--beamer_templete_prompt', type=str, default=None)
    parser.add_argument('--stage', type=str, default='["0"]')
    parser.add_argument('--arxiv_url', type=str, default=None)
    parser.add_argument('--openai_key', type=str, required=True, help='Your OpenAI API key')
    parser.add_argument('--gemini_key', type=str, required=True, help='Your Gemini API key')
    parser.add_argument('--logo_dir', type=str, required=True, help='Directory containing uploaded logo image(s)')
    args = parser.parse_args()
    print("start")

    try:
        args.openai_base_url, args.model_name_t, args.model_name_v = resolve_openai_settings(
            args.openai_base_url, args.model_name_t, args.model_name_v
        )
    except ValueError as error:
        parser.error(str(error))

    # ✅ 使用传入的 key 设置环境变量
    os.environ["OPENAI_API_KEY"] = args.openai_key
    if args.openai_base_url:
        os.environ["OPENAI_API_BASE_URL"] = args.openai_base_url
    else:
        os.environ.pop("OPENAI_API_BASE_URL", None)
    os.environ["GEMINI_API_KEY"] = args.gemini_key

    # 清空 output
    output_dir = ROOT_DIR / "output"
    if output_dir.exists():
        print(f"   🧹 Clearing old output directory: {output_dir.relative_to(ROOT_DIR)}")
        shutil.rmtree(output_dir)
    (output_dir / "latex_proj").mkdir(parents=True, exist_ok=True)
    (output_dir / "poster_latex_proj").mkdir(parents=True, exist_ok=True)
    (output_dir / "slide_imgs").mkdir(parents=True, exist_ok=True)
    print("   ✅ Created subfolders: latex_proj / poster_latex_proj / slide_imgs")

    # ================
    # Step 0: Download from arXiv
    # ================
    try:
        if args.arxiv_url:
            import requests, tarfile
            from io import BytesIO

            print(f"🧩 Step 0: Downloading from arXiv: {args.arxiv_url}")
            paper_id = args.arxiv_url.strip().split('/')[-1]
            input_dir = ROOT_DIR / "input"
            latex_proj_dir = input_dir / "latex_proj"

            if input_dir.exists():
                print(f"   🧹 Clearing old input directory: {input_dir.relative_to(ROOT_DIR)}")
                shutil.rmtree(input_dir)
            input_dir.mkdir(parents=True, exist_ok=True)
            latex_proj_dir.mkdir(parents=True, exist_ok=True)

            pdf_url = f"https://arxiv.org/pdf/{paper_id}.pdf"
            pdf_path = input_dir / "paper.pdf"
            print(f"   📄 Downloading PDF from {pdf_url} ...")
            r = requests.get(pdf_url)
            if r.status_code == 200:
                with open(pdf_path, 'wb') as f:
                    f.write(r.content)
                print(f"   ✅ Saved PDF → {pdf_path.relative_to(ROOT_DIR)}")
            else:
                raise RuntimeError(f"❌ Failed to download PDF (status {r.status_code})")

            src_url = f"https://arxiv.org/e-print/{paper_id}"
            print(f"   📦 Downloading LaTeX source from {src_url} ...")
            r = requests.get(src_url)
            if r.status_code == 200:
                try:
                    with tarfile.open(fileobj=BytesIO(r.content), mode="r:gz") as tar:
                        tar.extractall(path=latex_proj_dir)
                    print(f"   ✅ Extracted LaTeX source → {latex_proj_dir.relative_to(ROOT_DIR)}")
                except tarfile.ReadError:
                    print(f"   ⚠️  LaTeX source invalid, skipping.")
            else:
                print(f"   ⚠️  Failed to download LaTeX source.")
    except Exception as e:
        print(f"❌ Step 0 failed: {e}")

    # =========================
    # Step 1: Slide Generation
    # =========================
    # try:
    #     print("🧩 Step 1: Generating Slides ...")
    #     slide_latex_path = path.join(args.paper_latex_root, "slides.tex")
    #     slide_image_dir = path.join(args.result_dir, 'slide_imgs')
    #     os.makedirs(slide_image_dir, exist_ok=True)

    #     start_time = time.time()
    #     prompt_path = "./Paper2Video/src/prompts/slide_beamer_prompt.txt"

    #     if args.if_tree_search:
    #         usage_slide, beamer_path = latex_code_gen(
    #             prompt_path=prompt_path,
    #             tex_dir=args.paper_latex_root,
    #             beamer_save_path=slide_latex_path,
    #             model_config_ll=get_agent_config(args.model_name_t),
    #             model_config_vl=get_agent_config(args.model_name_v),
    #             beamer_temp_name=args.beamer_templete_prompt
    #         )
    #     else:
    #         paper_latex_path = path.join(args.paper_latex_root, "main.tex")
    #         usage_slide = latex_code_gen(
    #             prompt_path=prompt_path,
    #             tex_dir=args.paper_latex_root,
    #             tex_path=paper_latex_path,
    #             beamer_save_path=slide_latex_path,
    #             model_config=get_agent_config(args.model_name_t)
    #         )
    #         beamer_path = slide_latex_path

    #     if not os.path.exists(beamer_path):
    #         raise FileNotFoundError(f"❌ Beamer PDF not found: {beamer_path}")

    #     slide_imgs = convert_from_path(beamer_path, dpi=400)
    #     for i, img in enumerate(slide_imgs):
    #         img.save(path.join(slide_image_dir, f"{i+1}.png"))
    #     print("✅ Step 1 done.")
    # except Exception as e:
    #     print(f"❌ Step 1 failed: {e}")

    # =========================
    # Step 1.5: Poster2Poster 内容生成
    # =========================
    try:
        run_paper2poster_content_build()
    except Exception as e:
        print(f"❌ Step 1.5 failed: {e}")

    # =========================
    # Step 2: Build Poster
    # =========================
    try:
        print("🧩 Step 2: Building poster ...")
        build_poster()
        print("✅ Step 2 done.")
    except Exception as e:
        print(f"❌ Step 2 failed: {e}")

    # =========================
    # Step 3: 导出 latex_proj & 处理 LOGO & 应用 template
    # =========================
    try:
        src_lp = PB_ROOT / "latex_proj"
        dst_lp = ROOT_DIR / "output" / "poster_latex_proj"
        copytree_overwrite(src_lp, dst_lp)
        print(f"📦 Exported LaTeX project → {dst_lp.relative_to(ROOT_DIR)}")

        logo_dir = Path(args.logo_dir)
        logo_files = _list_logo_files(logo_dir)
        # if len(logo_files) == 0:
        #     raise RuntimeError("❌ No logo files found in --logo_dir (must upload at least one).")

        template_dir = ROOT_DIR / "template"
        if template_dir.exists():
            for item in template_dir.iterdir():
                dst_path = dst_lp / item.name
                if item.is_dir():
                    if dst_path.exists():
                        shutil.rmtree(dst_path)
                    shutil.copytree(item, dst_path)
                else:
                    shutil.copy2(item, dst_path)
            print(f"📂 Copied all template files → {dst_lp.relative_to(ROOT_DIR)}")
        else:
            print("⚠️ template directory not found, skipping Step 3.5.")

        logos_out_dir = dst_lp / "logos"
        # logos_out_dir.mkdir(parents=True, exist_ok=True)
        left_logo_path = logos_out_dir / "left_logo.png"

        if len(logo_files) == 1:
            # 单图：拷贝并转成 PNG（以确保一致）
            im = Image.open(logo_files[0]).convert("RGBA")
            im.save(left_logo_path, format="PNG")
            print(f"🖼️  Single logo saved → {left_logo_path.relative_to(ROOT_DIR)}")
        elif len(logo_files) > 1:
            # 多图：拼接
            _compose_logos_horizontally(logo_files, left_logo_path, box_w=2000, box_h=476, gap=16)

        print("✅ Step 3 done.")
    except Exception as e:
        print(f"❌ Step 3 failed: {e}")

    print("✅ Pipeline completed.")
