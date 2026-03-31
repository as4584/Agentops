import re

import requests
from bs4 import BeautifulSoup


def decode_secret_message(url):
    response = requests.get(url)
    soup = BeautifulSoup(response.text, "html.parser")

    grid = {}
    max_x = 0
    max_y = 0

    for tag in soup.find_all("tr", class_="c4"):
        t = tag.get_text().strip()
        match = re.fullmatch(r"(\d+)([░█])(\d+)", t)
        if match:
            x = int(match.group(1))
            char = match.group(2)
            y = int(match.group(3))
            grid[(x, y)] = char
            max_x = max(max_x, x)
            max_y = max(max_y, y)

    print(f"Grid: {max_x} x {max_y}, chars: {len(grid)}")

    for y in range(max_y, -1, -1):
        row = ""
        for x in range(max_x + 1):
            row += grid.get((x, y), " ")
        if row.strip():
            print(row.rstrip())


decode_secret_message(
    "https://docs.google.com/document/d/e/2PACX-1vSvM5gDlNvt7npYHhp_XfsJvuntUhq184By5xO_pA4b_gCWeXb6dM6ZxwN8rE6S4ghUsCj2VKR21oEP/pub"
)
