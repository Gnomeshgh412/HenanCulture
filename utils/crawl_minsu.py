from __future__ import annotations

"""
使用步骤：
1. 修改下面【参数设置区】里的：
   - URL_TEMPLATE（含 {id} 的网址模板）
   - START_ID / END_ID（起止 id）
   - TEXT_DIR（txt 输出目录）
   - IMAGE_DIR（图片输出目录）
   - TEXT_PREFIX（txt 文件名前缀）
   - PAGE_DIR_PREFIX（每个页面图片子目录名前缀）
   - IMAGE_NAME_TEMPLATE（图片名模板，默认 "1","2","3"...）

2. 安装依赖：
   pip install requests beautifulsoup4 lxml

3. 运行：
   python crawl_henan_minsu_param.py
"""
import lxml


#%%
import os
import sys
import time
import logging
from bs4 import BeautifulSoup
from bs4.element import Tag, NavigableString
from pathlib import Path
from urllib.parse import urljoin, urlsplit
import mimetypes

import requests
from bs4 import BeautifulSoup


#%%
# ==================  参数设置区（按需修改）  ==================

# 网址模板：其中 {id} 会被数字替换
URL = "https://db.lydswz.cn/BookContent.aspx?bookid=200904080017&contentid={id}&type=c&show=content"

# 要抓取的 id 范围（包含两端）
START_ID = 236717
END_ID = 236718

# 输出 txt 的目录
TEXT_DIR = Path("D:\\桌面\\New Life\\河南地方志中的民俗要素挖掘与知识图谱构建\\Data\\luoyang_city_gazetteer\\raw_data\\民俗研究\\01_民俗的整理与研究")

# 输出图片的根目录（每个页面再建一个子目录）
IMAGE_DIR = Path("D:\\桌面\\New Life\\河南地方志中的民俗要素挖掘与知识图谱构建\\Data\\luoyang_city_gazetteer\\raw_data\\民俗研究\\01_民俗的整理与研究\\image")

# txt 文件名前缀：最终形如
#   {TEXT_PREFIX}_{index:03d}_{page_id}.txt
TEXT_PREFIX = "luoyang_minsu"

# 每个页面图片子目录名前缀：最终形如
#   images/{PAGE_DIR_PREFIX}_{index:03d}_{page_id}/
PAGE_DIR_PREFIX = "luoyang_minsu"

# 单张图片文件名模板：
#   默认 "{num}" → 1.jpg, 2.jpg, 3.jpg ...
#   也可以改成 "img_{num}" → img_1.jpg, img_2.jpg ...
IMAGE_NAME_TEMPLATE = "{num}"

# 抓取间隔，防止过快
SLEEP_SECONDS = 0.5

#%%
# ==========================================================

# 尝试识别正文的候选 CSS 选择器（优先使用）
CANDIDATE_CONTENT_SELECTORS = [
    "#contentdiv",
    "#zoom",
    ".TRS_Editor",
    "#contentdiv",
    ".article-body",
    ".article",
    "#content",
    ".content",
]

# 块级标签：前后加空行，形成段落
BLOCK_TAGS = {
    "p", "div", "section", "article",
    "h1", "h2", "h3", "h4", "h5", "h6",
    "ul", "ol", "li",
    "blockquote", "pre",
}

# 换行标签
LINE_BREAK_TAGS = {"br", "hr"}

TIMEOUT = 30

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)

session = requests.Session()
session.trust_env = False  # 不使用系统环境变量里的代理

session.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "close",
    "Referer": "https://db.lydswz.cn/",
})


#%%
# -------------------- 工具函数 --------------------
def ensure_dirs():
    TEXT_DIR.mkdir(parents=True, exist_ok=True)
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)

#%%
def fetch_html(url: str) -> str | None:
    """抓取单个页面的 HTML 文本。"""
    try:
        # verify=False 先试一下是否是证书/中间代理问题
        resp = session.get(url, timeout=TIMEOUT, verify=False)
        resp.raise_for_status()
    except requests.exceptions.ReadTimeout:
        logging.warning("读取超时 %s", url)
        return None
    except Exception as e:
        logging.warning("请求失败 %s: %r", url, e)
        return None

    # 这里如果再次看到 header 的 warning，可以忽略
    if (resp.encoding or "").lower() == "iso-8859-1":
        resp.encoding = resp.apparent_encoding or "utf-8"
    else:
        resp.encoding = resp.encoding or "utf-8"

    return resp.text

#%%
def pick_content_tag(soup: BeautifulSoup):
    """从整页 HTML 中挑出正文所在的 Tag。"""
    # 1) 预设选择器
    for sel in CANDIDATE_CONTENT_SELECTORS:
        tag = soup.select_one(sel)
        if tag and tag.get_text(strip=True):
            return tag

    # 2) 兜底：找文本最多的 div/article
    best_tag = None
    best_len = 0
    for tag in soup.find_all(["div", "article"]):
        text = tag.get_text(strip=True)
        length = len(text)
        if length > best_len:
            best_len = length
            best_tag = tag

    if best_tag is None:
        best_tag = soup.body or soup

    return best_tag

#%%
def extract_text(content_tag) -> str:
    """从正文容器中提取纯文本。"""
    return content_tag.get_text("\n", strip=True)

#%%
def guess_image_extension(src_url: str, content_type: str | None) -> str:
    """根据 URL 或 Content-Type 猜测图片后缀，失败则默认 .jpg。"""
    path = urlsplit(src_url).path
    ext = os.path.splitext(path)[1].lower()
    if ext in {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"}:
        return ext

    if content_type:
        ext_guess = mimetypes.guess_extension(content_type.split(";")[0].strip())
        if ext_guess:
            return ext_guess

    return ".jpg"


def download_image(img_url: str, save_path_no_ext: Path):
    """下载单张图片到指定路径（不含后缀，内部自动补后缀）。"""
    try:
        resp = session.get(img_url, timeout=TIMEOUT)
    except Exception as e:
        logging.warning("图片下载失败 %s: %s", img_url, e)
        return

    if resp.status_code != 200:
        logging.warning("图片下载失败 %s: HTTP %s", img_url, resp.status_code)
        return

    content_type = resp.headers.get("Content-Type", "")
    ext = guess_image_extension(img_url, content_type)
    save_path = save_path_no_ext.with_suffix(ext)

    try:
        save_path.write_bytes(resp.content)
        logging.info("保存图片: %s", save_path)
    except Exception as e:
        logging.warning("写入图片失败 %s: %s", save_path, e)

#%%
# -------------------- 核心处理 --------------------
def process_page(page_id: int, index: int):
    """
    处理单个页面：
        - 抓取 HTML
        - 提取正文 -> txt
        - 抓取正文中的图片 -> images
    page_id: URL 中的数字部分（如 100352）
    index  : 第几个页面（从 1 开始），用于命名
    """
    url = URL.format(id=page_id)
    logging.info("处理页面 %s (index=%d)...", url, index)

    html = fetch_html(url)
    if not html:
        logging.warning("跳过页面 %s", url)
        return

    soup = BeautifulSoup(html, "lxml")
    content_tag = pick_content_tag(soup)

    # ------ 1. 保存 txt ------
    text = extract_text(content_tag)
    if not text.strip():
        logging.warning("页面 %s 正文为空，可能需要调整选择器", url)

    text_filename = f"{TEXT_PREFIX}_{index:03d}_{page_id}.txt"
    text_path = TEXT_DIR / text_filename
    text_path.write_text(text, encoding="utf-8")
    logging.info("保存文本: %s", text_path)

    # ------ 2. 保存图片 ------
    img_tags = content_tag.find_all("img")
    if not img_tags:
        logging.info("页面 %s 未发现图片", url)
        return

    subdir_name = f"{PAGE_DIR_PREFIX}_{index:03d}_{page_id}"
    img_subdir = IMAGE_DIR / subdir_name
    img_subdir.mkdir(parents=True, exist_ok=True)

    logging.info("页面 %s 共发现 %d 张图片", url, len(img_tags))

    for i, img in enumerate(img_tags, start=1):
        src = img.get("src")
        if not src:
            continue
        img_url = urljoin(url, src)

        # 图片名：根据 IMAGE_NAME_TEMPLATE 生成，如 "1" / "img_1" 等
        img_name_without_ext = IMAGE_NAME_TEMPLATE.format(num=i)
        save_no_ext = img_subdir / img_name_without_ext
        download_image(img_url, save_no_ext)

#%%
def main():
    ensure_dirs()
    index = 0
    for page_id in range(START_ID, END_ID + 1):
        process_page(page_id, index=index)
        index += 1
        time.sleep(SLEEP_SECONDS)

    logging.info("全部完成。")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logging.info("用户中断，退出。")
        sys.exit(0)
