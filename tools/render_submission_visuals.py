"""Render all native HTML diagrams without viewport cropping; check layout."""
from pathlib import Path
import json
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
NAMES = ['구상도_통합', '구상도_모바일', '구상도_데스크톱',
         '시스템_흐름도', '화면_아이', '화면_보호자', '화면_위험변화']

with sync_playwright() as pw:
    browser = pw.chromium.launch()
    for name in NAMES:
        page = browser.new_page(viewport={'width': 1540 if name != '구상도_모바일' else 500,
                                          'height': 900}, device_scale_factor=2)
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.goto((ROOT / (name + '.html')).as_uri())
        page.evaluate('document.fonts.ready')
        height = page.evaluate('Math.ceil(document.body.getBoundingClientRect().height)')
        page.set_viewport_size({'width':1540 if name != '구상도_모바일' else 500, 'height':height})
        text = page.locator('body').inner_text()
        assert '시안' in text or '계획' in text
        for banned in ['위험은 장소가 아니라', '가장 안전한 길', '화면 꺼짐', '판단부만 예측 엔진']:
            assert banned not in text, (name, banned)
        assert not errors, (name, errors)
        # Connector arrows deliberately extend into grid gaps; test content only.
        probe_style = page.add_style_tag(content='*::before,*::after{content:none!important}')
        layout = page.evaluate('''() => {
          const clipped = [...document.querySelectorAll('div,span,p')].filter(e => {
            const c = getComputedStyle(e);
            return e.clientWidth > 0 && (e.scrollWidth > e.clientWidth + 2 ||
              e.scrollHeight > e.clientHeight + 2) && c.display !== 'inline';
          }).map(e => ({cls:e.className, text:e.innerText.slice(0,65),
            w:[e.clientWidth,e.scrollWidth], h:[e.clientHeight,e.scrollHeight]}));
          return {width:document.documentElement.scrollWidth,
            height:document.documentElement.scrollHeight, clipped};
        }''')
        probe_style.evaluate('(e) => e.remove()')
        assert not layout['clipped'], (name, layout['clipped'])
        page.screenshot(path=str(ROOT / '이미지' / (name + '.png')), full_page=True)
        print(json.dumps({'name':name, **layout, 'result':'PASS'}, ensure_ascii=False))
        page.close()
    browser.close()
