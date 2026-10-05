import re


def sort_video_files(files):
    def parse_ep(name):
        m = re.search(r'S(\d+)E(\d+)', name, re.IGNORECASE)
        if m: return (1, int(m.group(1)), int(m.group(2)), name)
        m = re.search(r'(\d+)x(\d+)', name, re.IGNORECASE)
        if m: return (1, int(m.group(1)), int(m.group(2)), name)
        return (0, 0, 0, name)
    return sorted(files, key=lambda f: parse_ep(f.get("name", "")))