"""產生 Phase 2C-A 評測用的合成 fixture 圖片（不需要真實照片）。

全部是程式繪製的文字圖／雜訊圖 —— 沒有任何個人資料，可以安全送給
外部 provider（free tier 內容政策下也僅有這些合成圖）。

用法：
    python tools/make_eval_images.py

輸出：tools/eval_fixtures/images/*.jpg（已 commit；重跑會覆蓋成相同內容）
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(__file__).resolve().parent / "eval_fixtures" / "images"

#: 優先序：微軟正黑體（含中文與拉丁）→ 其他常見字型。
FONT_CANDIDATES = (
    r"C:\Windows\Fonts\msjh.ttc",
    r"C:\Windows\Fonts\msyh.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    r"C:\Windows\Fonts\arial.ttf",
)

SIZE = (800, 600)


def _font(size: int) -> ImageFont.FreeTypeFont:
    for path in FONT_CANDIDATES:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except Exception:  # noqa: BLE001 - 換下一個候選
                continue
    raise SystemExit("找不到可用字型；請在 FONT_CANDIDATES 加入本機字型路徑")


def text_image(name: str, lines: tuple[str, ...], *, big_first: bool = False) -> None:
    """白底黑字的文字圖（標籤／收據）。"""
    image = Image.new("RGB", SIZE, (250, 250, 246))
    draw = ImageDraw.Draw(image)
    draw.rectangle((8, 8, SIZE[0] - 8, SIZE[1] - 8), outline=(180, 180, 180), width=2)
    y = 36
    for index, line in enumerate(lines):
        size = 72 if (big_first and index == 0) else 42
        draw.text((36, y), line, font=_font(size), fill=(20, 20, 24))
        y += size + 16
    image.save(OUT / name, "JPEG", quality=90)
    print(f"wrote {name}")


def noise_image(name: str, seed: int) -> None:
    """無文字的雜訊／色塊圖（模擬拍不清楚或輔助照片）。"""
    rng = random.Random(seed)
    image = Image.new("RGB", SIZE, (60, 60, 66))
    draw = ImageDraw.Draw(image)
    for _ in range(180):
        x = rng.randrange(0, SIZE[0])
        y = rng.randrange(0, SIZE[1])
        r = rng.randrange(6, 48)
        shade = rng.randrange(70, 170)
        draw.ellipse((x - r, y - r, x + r, y + r),
                     fill=(shade, shade, shade + rng.randrange(-12, 12)))
    image.save(OUT / name, "JPEG", quality=85)
    print(f"wrote {name}")


def unknown_part_image(name: str) -> None:
    """沒有文字的暗色零件圖（不確定物件）。"""
    image = Image.new("RGB", SIZE, (46, 48, 54))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((180, 150, 620, 470), radius=40, fill=(120, 122, 128))
    draw.ellipse((240, 210, 380, 350), fill=(90, 92, 98))
    draw.ellipse((440, 240, 540, 340), fill=(150, 152, 158))
    for offset in range(0, 9):
        draw.line((190, 160 + offset * 34, 610, 176 + offset * 34),
                  fill=(70, 72, 78), width=2)
    image.save(OUT / name, "JPEG", quality=88)
    print(f"wrote {name}")


def dark_image(name: str) -> None:
    """幾乎全黑的照片（證據不足）。"""
    rng = random.Random(7)
    image = Image.new("RGB", SIZE, (16, 16, 18))
    draw = ImageDraw.Draw(image)
    for _ in range(60):
        x = rng.randrange(0, SIZE[0])
        y = rng.randrange(0, SIZE[1])
        value = rng.randrange(22, 34)
        draw.point((x, y), fill=(value, value, value))
    image.save(OUT / name, "JPEG", quality=85)
    print(f"wrote {name}")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)

    # L1：清楚的商品標籤
    text_image("label_sony.jpg",
               ("SONY", "WH-1000XM5", "Serial No. 4528653", "Made in Malaysia"),
               big_first=True)

    # L2 / L3：無法辨識的零件
    unknown_part_image("unknown_part.jpg")

    # L3：之後補上的收據（會改變品名與屬性）
    text_image("receipt_makita.jpg",
               ("光華商場", "電子發票證明聯",
                "品名: 牧田 18V 震動電鑽", "型號: DHP484",
                "金額: NT$12,900", "日期: 2026-05-10"))

    # L4：互相矛盾的兩份證據（標籤 vs 發票）
    text_image("label_toshiba.jpg",
               ("TOSHIBA", "2TB HDD", "MODEL: DT01ACA200", "SN: X4T2ABC"),
               big_first=True)
    text_image("receipt_seagate.jpg",
               ("PChome 電子發票", "SEAGATE 2TB 硬碟",
                "金額: NT$1,890", "日期: 2026-03-02"))

    # L5：幾乎全黑
    dark_image("dark_blank.jpg")

    # L6：九張照片的紀錄 —— 最早的是身份標籤，之後是背帶收據與雜訊
    text_image("label_nikon.jpg",
               ("Nikon", "AF-S NIKKOR 50mm f/1.8G", "Serial No. 2234567"),
               big_first=True)
    text_image("receipt_strap.jpg",
               ("相機王", "相機背帶", "金額: NT$690", "日期: 2026-06-01"))
    for index in range(2, 9):
        noise_image(f"noise_{index:02d}.jpg", seed=100 + index)


if __name__ == "__main__":
    sys.exit(main())
