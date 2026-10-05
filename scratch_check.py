import os

with open('static/index.html', 'r', encoding='utf-8') as f:
    for i, line in enumerate(f):
        if 'meta-search-results' in line or 'lib-list' in line or 'detail-files' in line:
            print(f'{i+1}: {line.strip()}')
