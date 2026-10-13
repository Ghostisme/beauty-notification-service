"""从同一份中文步骤生成离线可读、可打印的后台操作手册。"""
import hashlib
import re
from pathlib import Path
from urllib.parse import quote

import markdown


ROOT = Path(__file__).resolve().parent.parent
DOCS_BASE = "https://github.com/Ghostisme/beauty-notification-service/blob/feature/laike-wecom-tool/laike-wecom-tool/docs/"


def section_id(value, separator):
    number = re.match(r"(\d{2})\s*·", value)
    return "section-" + (number[1] if number else hashlib.sha1(value.encode("utf-8")).hexdigest()[:8])


def main():
    source = (ROOT / "docs" / "操作手册.md").read_text(encoding="utf-8")
    source = source.split("\n", 1)[1]
    source = re.sub(r"\]\(([^():]+\.md)\)", lambda match: "](" + DOCS_BASE + quote(match[1]) + ")", source)
    renderer = markdown.Markdown(extensions=["toc", "tables", "fenced_code", "sane_lists"],
                                 extension_configs={"toc":{"toc_depth":"2-2", "slugify":section_id}})
    content = renderer.convert(source)
    page = '''<!doctype html>
<html lang="zh-CN">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>来客门店通知工具 · 操作手册</title><link rel="stylesheet" href="manual.css"></head>
<body><header class="masthead"><div class="brand">来客门店通知工具</div><span>Windows / Apple 芯片 Mac</span></header>
<div class="layout"><aside class="contents"><p class="nav-title">按需要找步骤</p>TOC
<p class="nav-note">首次安装按顺序执行。日常运营主要看 08、09；服务器维护看 01、10。</p>
<a class="back" href="https://notification.hongquanquan.cn">打开线上后台 ↗</a></aside>
<main><section class="hero"><p class="eyebrow">安装 · 实测 · 日常操作</p><h1>来客通知，按步骤用起来。</h1>
<p>从真实抖音数据，到对应门店的企微外部客户群。<br>一份手册，完成部署、Mac 登录、测试和人工处理。</p>
<div class="quick-links"><a href="#section-03">我先安装 Mac →</a><a href="#section-08">我查看日常操作 →</a><a href="#section-01">我来部署服务器 →</a></div></section>
<article>CONTENT</article><footer>手册版本：2026-10-13 · 代码分支 feature/laike-wecom-tool · 可用浏览器打印或保存</footer></main></div></body></html>'''
    page = page.replace("TOC",renderer.toc).replace("CONTENT",content)
    target = ROOT / "toolbox" / "static" / "manual.html"
    target.write_text(page,encoding="utf-8")
    print("浏览器版操作手册已生成：" + str(target.relative_to(ROOT)))


if __name__ == "__main__":main()
