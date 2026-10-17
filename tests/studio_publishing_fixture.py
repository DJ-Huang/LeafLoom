"""Synthetic, user-data-free publishing fixture shared by browser/export checks."""
ART_SVG = '''<svg xmlns="http://www.w3.org/2000/svg" width="360" height="240" viewBox="0 0 360 240"><rect width="360" height="240" fill="#e8eef8"/><circle cx="120" cy="100" r="64" fill="#526ee8"/><path d="M170 210 260 50 340 210Z" fill="#e9a650"/></svg>'''


def fixture_document():
    bindings = {'shared.art': {'key': 'shared.art', 'kind': 'image', 'value': 'shared-art', 'revision': 1}}
    pages = []
    for index in range(1, 6):
        key = f'page.{index}.title'
        bindings[key] = {'key': key, 'kind': 'text', 'value': f'Creative collection {index}', 'revision': 1}
        pages.append({'id': f'page-{index}', 'name': f'Collection {index}', 'group': 'Publishing fixture', 'width': 720, 'height': 900,
                      'background': '#ffffff', 'nodes': [
                          {'id': f'art-{index}', 'name': 'Shared artwork, no text', 'type': 'image',
                           'style': {'x': 60, 'y': 60, 'width': 600, 'height': 400},
                           'props': {'assetId': 'shared-art', 'bindingKey': 'shared.art'}, 'children': []},
                          {'id': f'title-{index}', 'name': 'Editable collection title', 'type': 'text',
                           'style': {'x': 60, 'y': 500, 'width': 600, 'height': 180, 'fontSize': 48, 'color': '#172b4d'},
                           'props': {'text': bindings[key]['value'], 'bindingKey': key}, 'children': []},
                          {'id': f'caption-{index}', 'name': 'Independent editable caption', 'type': 'text',
                           'style': {'x': 60, 'y': 720, 'width': 600, 'height': 80, 'fontSize': 24},
                           'props': {'text': f'Studio sample {index}'}, 'children': []}]})
    variants = {}
    for locale, title in [('en', 'Creative collection'), ('ja', 'クリエイティブ コレクション'), ('zh', '创意作品集')]:
        values = {'shared.art': {'value': 'shared-art', 'sourceRevision': 1}}
        values.update({f'page.{index}.title': {'value': f'{title} {index}', 'sourceRevision': 1} for index in range(1, 6)})
        variants[locale] = {'id': locale, 'name': {'en': 'English', 'ja': '日本語', 'zh': '简体中文'}[locale], 'locale': locale,
                            'context': {'campaign': 'synthetic-launch'}, 'values': values,
                            'layout': {f'title-{index}': {'fontSize': 40 if locale == 'ja' else 48, 'height': 190} for index in range(1, 6)},
                            'pageLayout': {}}
    return {'schemaVersion': 1, 'id': 'studio-publishing-fixture', 'name': 'Studio publishing fixture', 'pages': pages,
            'assets': {'shared-art': {'id': 'shared-art', 'name': 'Shared text-free artwork', 'path': 'Design/Assets/shared-art.svg', 'mime': 'image/svg+xml'}},
            'components': {}, 'scripts': {}, 'styles': {}, 'bindings': bindings, 'variants': variants}
