"""Every component icon must be a straight copy of a source file under parment/svg."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COMPONENTS = ROOT / 'icon' / 'components'
SOURCE = ROOT / 'parment' / 'svg'
CSS = ROOT / 'web' / 'component-icons.css'


class TestComponentIcons(unittest.TestCase):
    def test_every_component_icon_exists(self):
        assert COMPONENTS.is_dir(), COMPONENTS
        assert list(COMPONENTS.glob('*.svg')), '没有找到组件图标'

    def test_component_icons_are_copied_verbatim_from_parment(self):
        missing = []
        for path in sorted(COMPONENTS.glob('*.svg')):
            source = SOURCE / path.name
            if not source.exists():
                missing.append(f'{path.name}（parment/svg 中没有同名文件）')
            elif source.read_bytes() != path.read_bytes():
                missing.append(f'{path.name}（与 parment/svg 不一致，应重新拷贝）')
        assert not missing, '；'.join(missing)

    def test_css_only_references_shipped_icons(self):
        declared = set(re.findall(r'\[data-icon="([^"]+)"\]\s*\{[^}]*url\("/icon/components/([^"]+)"\)',
                                  CSS.read_text(encoding='utf-8')))
        broken = [(name, file) for name, file in declared if not (COMPONENTS / file).exists()]
        assert not broken, f'CSS 引用了不存在的图标：{broken}'


if __name__ == '__main__':
    unittest.main()
