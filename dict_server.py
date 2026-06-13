#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
中文词典查词工具 - Web服务器版本
无需任何外部依赖，只使用 Python 内置库
"""

import json
import re
import os
from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.parse import parse_qs, urlparse
from pathlib import Path


class DictParser:
    """词典解析器"""

    # 基础声母表（23 个）
    BASE_INITIALS = [
        'b', 'p', 'm', 'f', 'd', 't', 'n', 'l',
        'g', 'k', 'h', 'j', 'q', 'x',
        'zh', 'ch', 'sh', 'r', 'z', 'c', 's',
        'y', 'w'
    ]

    # 整体认读音节（16 个）
    COMPLETE_SYLLABLES = [
        'zhi', 'chi', 'shi', 'ri', 'zi', 'ci', 'si',
        'yi', 'wu', 'yu', 'ye', 'yue', 'yuan',
        'yin', 'yun', 'ying'
    ]

    # 声母表（基础声母 + 整体认读音节 作为特殊声母）
    INITIALS_LIST = BASE_INITIALS + COMPLETE_SYLLABLES

    # 韵母表（24 个）
    FINALS_LIST = [
        'a', 'o', 'e', 'i', 'u', 'v', 'ai', 'ei', 'ui',
        'ao', 'ou', 'iu', 'ie', 've', 'er',
        'an', 'en', 'in', 'un', 'vn',
        'ang', 'eng', 'ing', 'ong'
    ]

    def __init__(self):
        self.entries = []

    # ----------------------------------------------------------------------
    # 词典加载
    # ----------------------------------------------------------------------
    def load_dictionary(self, file_paths):
        """加载词典文件，返回实际读取的条目数"""
        self.entries = []
        seen = set()

        if isinstance(file_paths, str):
            file_paths = [file_paths]

        for file_path in file_paths:
            if not os.path.exists(file_path):
                continue

            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith('#') or not line:
                            continue

                        entry = self._parse_entry(line)
                        if entry:
                            key = entry['simplified']
                            if key not in seen:
                                seen.add(key)
                                self.entries.append(entry)
            except Exception as e:
                print(f"Error reading {file_path}: {e}")

        return len(self.entries)

    # ----------------------------------------------------------------------
    # 单行解析
    # ----------------------------------------------------------------------
    def _parse_entry(self, line):
        """
        词条格式（CC‑CEDICT）:
        传统 字 简体 [拼音] /释义1/释义2/...
        """
        match = re.match(r'(.+?)\s+(.+?)\s+\[(.+?)\]\s+/(.+)/', line)
        if not match:
            return None

        traditional, simplified, pinyin, definitions = match.groups()
        pinyins = [p.strip() for p in pinyin.split()]

        entry = {
            'traditional': traditional,
            'simplified' : simplified,
            'pinyin'     : pinyins,
            'definitions': definitions,
            'char_count' : len(simplified),
            'initials'   : [self._get_initial(p) for p in pinyins],
            'finals'     : [self._get_final(p)   for p in pinyins],
            'tones'      : [self._get_tone(p)    for p in pinyins],
        }
        return entry

    # ----------------------------------------------------------------------
    # 声母、韵母、声调提取
    # ----------------------------------------------------------------------
    def _get_initial(self, pinyin):
        """提取声母（若为整体认读音节则直接返回该音节）"""
        pinyin_clean = re.sub(r'\d', '', pinyin).lower()
        if pinyin_clean in self.COMPLETE_SYLLABLES:
            return pinyin_clean

        for init in ['zh', 'ch', 'sh']:
            if pinyin_clean.startswith(init):
                return init

        for init in self.BASE_INITIALS:
            if init not in ['zh', 'ch', 'sh'] and pinyin_clean.startswith(init):
                return init
        return ''

    def _get_final(self, pinyin):
        """提取韵母（整体认读音节返回空字符串）"""
        pinyin_clean = re.sub(r'\d', '', pinyin).lower()
        if pinyin_clean in self.COMPLETE_SYLLABLES:
            return ''

        initial = self._get_initial(pinyin)
        if not initial:
            return pinyin_clean

        if initial in ['zh', 'ch', 'sh']:
            return pinyin_clean[2:] if len(pinyin_clean) > 2 else ''
        else:
            return pinyin_clean[1:] if len(pinyin_clean) > 1 else ''

    def _get_tone(self, pinyin):
        """提取声调（1‑4 为四声，缺省或非数字为轻声 5）"""
        match = re.search(r'(\d)$', pinyin)
        return int(match.group(1)) if match else 5

    # ----------------------------------------------------------------------
    # 筛选相关
    # ----------------------------------------------------------------------
    def get_available_filters(self):
        """返回前端可用的声母和韵母列表"""
        return {
            'initials': self.INITIALS_LIST,
            'finals'  : self.FINALS_LIST,
        }

    def filter_entries(self, filters):
        """根据提供的过滤条件返回匹配的词条"""
        results = self.entries[:]

        # ---------- 按整体字数过滤 ----------
        char_count_raw = filters.get('char_count')
        if char_count_raw:
            char_count_raw = char_count_raw.strip()
            if char_count_raw.isdigit():
                char_count = int(char_count_raw)
                results = [e for e in results if e['char_count'] == char_count]

        # ---------- 按逐字属性过滤 ----------
        if filters.get('by_char_filters'):
            results = self._filter_by_char(results, filters['by_char_filters'])

        # ---------- 包含/排除特定文字 ----------
        if filters.get('include_chars'):
            include = [c.strip() for c in filters['include_chars'].split(',') if c.strip()]
            if include:
                results = [e for e in results if any(c in e['simplified'] for c in include)]

        if filters.get('exclude_chars'):
            exclude = [c.strip() for c in filters['exclude_chars'].split(',') if c.strip()]
            if exclude:
                results = [e for e in results if not any(c in e['simplified'] for c in exclude)]

        return results

    def _filter_by_char(self, entries, char_filters):
        """逐字（位置）过滤，采用严格的 AND 逻辑"""
        matched = []
        for entry in entries:
            pinyins = entry['pinyin']
            initials = entry['initials']
            finals   = entry['finals']
            tones    = entry['tones']

            ok = True
            for pos_str, cond in char_filters.items():
                try:
                    pos = int(pos_str)            # 已经是 0‑based
                    if pos >= len(pinyins):
                        ok = False
                        break

                    # 声调过滤
                    if cond.get('tones'):
                        filter_tones = [int(t) for t in cond['tones']]
                        if tones[pos] not in filter_tones:
                            ok = False
                            break

                    # 声母过滤
                    if cond.get('initials'):
                        if initials[pos] not in cond['initials']:
                            ok = False
                            break

                    # 韵母过滤
                    if cond.get('finals'):
                        if finals[pos] not in cond['finals']:
                            ok = False
                            break
                except (ValueError, IndexError):
                    ok = False
                    break

            if ok:
                matched.append(entry)
        return matched


# ----------------------------------------------------------------------
# 全局词典实例（在服务启动后保持）
# ----------------------------------------------------------------------
g_parser = DictParser()


# ----------------------------------------------------------------------
# HTTP 请求处理
# ----------------------------------------------------------------------
class DictRequestHandler(SimpleHTTPRequestHandler):
    """处理前端页面及 API 请求"""

    # --------------------------- GET ---------------------------
    def do_GET(self):
        parsed_path = urlparse(self.path)
        path = parsed_path.path

        if path == '/':
            self._serve_html()
        elif path == '/api/load':
            self._api_load()
        elif path == '/api/filters':
            self._api_filters()
        elif path == '/api/search':
            self._api_search()
        else:
            self.send_response(404)
            self.end_headers()

    # --------------------------- 页面 ---------------------------
    def _serve_html(self):
        """返回前端页面（若不存在 index.html 则返回提示）"""
        self.send_response(200)
        self.send_header('Content-type', 'text/html; charset=utf-8')
        self.end_headers()

        html_path = os.path.join(os.path.dirname(__file__), 'index.html')
        if os.path.exists(html_path):
            with open(html_path, 'rb') as f:
                self.wfile.write(f.read())
        else:
            self.wfile.write(self._get_default_html().encode('utf-8'))

    def _get_default_html(self):
        return '''<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><title>错误</title></head>
<body><h1>错误：找不到 index.html 文件</h1></body>
</html>'''

    # --------------------------- API: 加载词典 ---------------------------
    def _api_load(self):
        """前端调用：加载指定路径的词典文件"""
        try:
            query = parse_qs(urlparse(self.path).query)
            # 默认示例路径，可自行修改
            path = query.get('path', [''])[0]

            count = g_parser.load_dictionary(path)
            filters = g_parser.get_available_filters()

            response = {
                'success': True,
                'count'  : count,
                'initials': filters['initials'],
                'finals'  : filters['finals'],
            }
        except Exception as e:
            response = {'success': False, 'error': str(e)}

        self._send_json(response)

    # --------------------------- API: 获取过滤选项 ---------------------------
    def _api_filters(self):
        """前端调用：获得声母、韵母列表用于下拉框"""
        try:
            filters = g_parser.get_available_filters()
            response = {
                'success': True,
                'initials': filters['initials'],
                'finals'  : filters['finals'],
            }
        except Exception as e:
            response = {'success': False, 'error': str(e)}
        self._send_json(response)

    # --------------------------- API: 检索 ---------------------------
    def _api_search(self):
        """前端调用：根据用户输入的各种过滤条件返回匹配词条"""
        try:
            query = parse_qs(urlparse(self.path).query)

            # ---------- 整体字数 ----------
            char_count = query.get('char_count', [''])[0]

            # ---------- 按字的细粒度过滤 ----------
            by_char_filters = {}
            for key, values in query.items():
                if not key.startswith('char_'):
                    continue

                parts = key.split('_')
                # 必须形如 char_<位置>_<属性>，位置必须是数字
                if len(parts) < 3 or not parts[1].isdigit():
                    # 例如 char_count 就会在这里直接跳过
                    continue

                # 前端传来的位置是 1‑based，转为 0‑based 方便内部处理
                pos = str(int(parts[1]) - 1)
                filter_type = '_'.join(parts[2:])

                if pos not in by_char_filters:
                    by_char_filters[pos] = {}

                if filter_type == 'tones':
                    by_char_filters[pos]['tones'] = [int(v) for v in values if v.isdigit()]
                elif filter_type == 'initials':
                    by_char_filters[pos]['initials'] = values
                elif filter_type == 'finals':
                    by_char_filters[pos]['finals'] = values

            filters = {
                'char_count'      : char_count,
                'by_char_filters': by_char_filters if by_char_filters else None,
                'include_chars'   : query.get('include_chars', [''])[0],
                'exclude_chars'   : query.get('exclude_chars', [''])[0],
            }

            results = g_parser.filter_entries(filters)

            # ---------- 前端勾选哪些字段需要展示 ----------
            show_traditional = query.get('show_traditional', ['false'])[0].lower() == 'true'
            show_simplified  = query.get('show_simplified',  ['false'])[0].lower() == 'true'
            show_definitions = query.get('show_definitions', ['false'])[0].lower() == 'true'

            response = {
                'success'        : True,
                'total'          : len(results),
                'results'        : results[:1000],   # 防止一次性返回过多
                'show_traditional': show_traditional,
                'show_simplified' : show_simplified,
                'show_definitions': show_definitions,
            }
        except Exception as e:
            response = {'success': False, 'error': str(e)}

        self._send_json(response)

    # --------------------------- 辅助：返回 JSON ---------------------------
    def _send_json(self, data):
        self.send_response(200)
        self.send_header('Content-type', 'application/json; charset=utf-8')
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))

    # --------------------------- 抑制默认日志 ---------------------------
    def log_message(self, format, *args):
        pass


# ----------------------------------------------------------------------
# 程序入口
# ----------------------------------------------------------------------
def main():
    port = 6678
    server_address = ('', port)
    httpd = HTTPServer(server_address, DictRequestHandler)
    print(f"\n词典工具服务启动成功！")
    print(f"请在浏览器中打开: http://localhost:{port}")
    print(f"按 Ctrl+C 停止服务器\n")

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n服务器已停止")
        httpd.server_close()


if __name__ == '__main__':
    main()
