"""Fixed task set for bench/codemode_bench.py.

Every task runs on a fresh copy of a small Python repo (``shop``) with real files and real pytest.
Each task carries two hand-written trajectories that do the *same work*:

* ``steps``  - the call-per-tool way: a list of model messages, each a list of tool calls
  (one call per message unless the calls are independent reads).
* ``cm``     - the codemode way: model messages whose tool call is usually one ``codemode`` program
  (a model may still call a tool directly when one call is all it needs).

``check(repo, final)`` decides pass/fail from the repo state (tests) and/or the final answer.
These are deterministic replays: they measure the *harness* cost of doing the same work
(model calls, prompt tokens, wall time), not how well a model chooses what to do.
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

PY = sys.executable
PYTEST = f"{PY} -m pytest -q -p no:cacheprovider"

FILES: dict[str, str] = {
    "shop/__init__.py": '"""Toko kecil untuk bench codemode."""\nVERSION = "0.3.1"\n',
    "shop/config.py": (
        "TAX_RATE = 0.11\nCURRENCY = 'IDR'\nMAX_ITEMS = 50\nDISCOUNT_CODES = {'HEMAT10': 0.10, 'HEMAT25': 0.25}\n"
        "# TODO: pindahkan ke file .toml\n"),
    "shop/pricing.py": (
        "from shop.config import DISCOUNT_CODES\n\n\n"
        "def apply_discount(total, code):\n"
        "    \"\"\"Total setelah kode diskon (kode tak dikenal = tanpa diskon).\"\"\"\n"
        "    rate = DISCOUNT_CODES.get(code, 0)\n"
        "    return total * (1 - rate)\n\n\n"
        "def unit_price(item):\n"
        "    return item['price']\n\n\n"
        "def line_total(item):\n"
        "    return unit_price(item) * item['qty']\n"),
    "shop/tax.py": (
        "from shop.config import TAX_RATE\n\n\n"
        "def add_tax(amount):\n"
        "    \"\"\"Jumlah + PPN, dibulatkan ke rupiah terdekat.\"\"\"\n"
        "    return int(amount * (1 + TAX_RATE))  # BUG: memotong, bukan membulatkan\n\n\n"
        "def tax_of(amount):\n"
        "    return add_tax(amount) - amount\n"),
    "shop/cart.py": (
        "from shop.config import MAX_ITEMS\n"
        "from shop.pricing import apply_discount, line_total\n"
        "from shop.tax import add_tax\n\n\n"
        "class Cart:\n"
        "    def __init__(self):\n"
        "        self.items = []\n\n"
        "    def add(self, name, price, qty=1):\n"
        "        if len(self.items) >= MAX_ITEMS:\n"
        "            raise ValueError('keranjang penuh')\n"
        "        self.items.append({'name': name, 'price': price, 'qty': qty})\n\n"
        "    def subtotal(self):\n"
        "        return sum(line_total(i) for i in self.items)\n\n"
        "    def total(self, code=None):\n"
        "        # TODO: diskon setelah pajak atau sebelum?\n"
        "        return add_tax(apply_discount(self.subtotal(), code))\n"),
    "shop/inventory.py": (
        "class Inventory:\n"
        "    def __init__(self):\n"
        "        self.stock = {}\n\n"
        "    def restock(self, name, qty):\n"
        "        self.stock[name] = self.stock.get(name, 0) + qty\n\n"
        "    def take(self, name, qty):\n"
        "        have = self.stock.get(name, 0)\n"
        "        if qty > have + 1:  # BUG: off-by-one, harus qty > have\n"
        "            raise ValueError('stok kurang')\n"
        "        self.stock[name] = have - qty\n"
        "        return self.stock[name]\n\n"
        "    def low(self, limit=3):\n"
        "        return sorted(n for n, q in self.stock.items() if q <= limit)\n"),
    "shop/report.py": (
        "from shop.pricing import apply_discount\n\n\n"
        "def daily_summary(carts, code=None):\n"
        "    \"\"\"Ringkasan harian: jumlah keranjang dan omzet setelah diskon.\"\"\"\n"
        "    revenue = sum(apply_discount(c.subtotal(), code) for c in carts)\n"
        "    return {'carts': len(carts), 'revenue': revenue}\n\n\n"
        "def format_idr(n):\n"
        "    # TODO: pemisah ribuan titik\n"
        "    return f'Rp{n:,.0f}'\n"),
    "tests/__init__.py": "",
    "tests/test_pricing.py": (
        "from shop.pricing import apply_discount, line_total\n\n\n"
        "def test_discount():\n    assert apply_discount(100, 'HEMAT10') == 90\n\n\n"
        "def test_unknown_code():\n    assert apply_discount(100, 'XX') == 100\n\n\n"
        "def test_line_total():\n    assert line_total({'price': 5, 'qty': 3}) == 15\n"),
    "tests/test_tax.py": (
        "from shop.tax import add_tax, tax_of\n\n\n"
        "def test_add_tax_rounds():\n    assert add_tax(1999) == 2219  # 1999 * 1.11 = 2218.89\n\n\n"
        "def test_tax_of():\n    assert tax_of(1000) == 110\n"),
    "tests/test_inventory.py": (
        "import pytest\n\nfrom shop.inventory import Inventory\n\n\n"
        "def test_take_ok():\n    inv = Inventory(); inv.restock('teh', 2)\n    assert inv.take('teh', 2) == 0\n\n\n"
        "def test_take_too_many():\n    inv = Inventory(); inv.restock('teh', 2)\n"
        "    with pytest.raises(ValueError):\n        inv.take('teh', 3)\n"),
    "tests/test_cart.py": (
        "from shop.cart import Cart\n\n\n"
        "def test_cart_total():\n    c = Cart(); c.add('kopi', 1000, 2)\n    assert c.total() == 2220\n"),
}


def setup_repo(root: Path) -> None:
    for rel, text in FILES.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")


def tests_pass(repo: Path, target: str = "tests") -> bool:
    r = subprocess.run(f"{PYTEST} {target}", shell=True, cwd=repo, capture_output=True, text=True, timeout=120)
    return r.returncode == 0


Call = tuple[str, dict]


@dataclass
class Task:
    id: str
    prompt: str
    steps: list[list[Call]]
    cm: list[list[Call]]
    final: str
    check: Callable[[Path, str], bool]
    kind: str = "code"
    notes: str = ""
    tags: list[str] = field(default_factory=list)


def _cm(code: str) -> list[Call]:
    return [("codemode", {"code": code.strip("\n")})]


TAX_FIX_OLD = "    return int(amount * (1 + TAX_RATE))  # BUG: memotong, bukan membulatkan"
TAX_FIX_NEW = "    return round(amount * (1 + TAX_RATE))"
INV_OLD = "        if qty > have + 1:  # BUG: off-by-one, harus qty > have"
INV_NEW = "        if qty > have:"

TASKS: list[Task] = [
    Task(
        id="qna-discount-callers", kind="qna",
        prompt="Di mana apply_discount didefinisikan dan siapa saja yang memanggilnya?",
        steps=[[("grep", {"pattern": "apply_discount"})],
               [("read_file", {"path": "shop/pricing.py"})],
               [("read_file", {"path": "shop/cart.py"})],
               [("read_file", {"path": "shop/report.py"})]],
        cm=[_cm("""
hits = tools.grep(pattern='apply_discount')
files = sorted({l.split(':', 1)[0] for l in hits.splitlines() if l.endswith('.py') or '.py:' in l})
print(hits)
""")],
        final="apply_discount didefinisikan di shop/pricing.py; dipanggil oleh Cart.total (shop/cart.py) dan "
              "daily_summary (shop/report.py), plus tes tests/test_pricing.py.",
        check=lambda repo, final: all(s in final for s in ("shop/pricing.py", "shop/cart.py", "shop/report.py")),
    ),
    Task(
        id="fix-tax-rounding",
        prompt="Tes pajak gagal. Perbaiki bug-nya dan pastikan semua tes hijau.",
        steps=[[("shell", {"command": f"{PYTEST} tests"})],
               [("read_file", {"path": "tests/test_tax.py"})],
               [("read_file", {"path": "shop/tax.py"})],
               [("edit_file", {"path": "shop/tax.py", "old_string": TAX_FIX_OLD, "new_string": TAX_FIX_NEW})],
               [("shell", {"command": f"{PYTEST} tests/test_tax.py tests/test_cart.py"})]],
        cm=[_cm(f"""
run, t, src = tools.parallel([('shell', {{'command': {PYTEST!r} + ' tests'}}),
                              ('read_file', {{'path': 'tests/test_tax.py'}}),
                              ('read_file', {{'path': 'shop/tax.py'}})])
print('\\n'.join(l for l in run.splitlines() if 'FAILED' in l or 'assert' in l)[:1500])
print(src)
"""), _cm(f"""
print(tools.edit_file(path='shop/tax.py', old_string={TAX_FIX_OLD!r}, new_string={TAX_FIX_NEW!r}))
print(tools.shell(command={PYTEST!r} + ' tests/test_tax.py tests/test_cart.py').strip().splitlines()[-1])
""")],
        final="add_tax memotong (int) alih-alih membulatkan; diganti round(). Tes pajak dan keranjang hijau.",
        check=lambda repo, final: tests_pass(repo, "tests/test_tax.py tests/test_cart.py"),
    ),
    Task(
        id="qna-todos", kind="qna",
        prompt="Ada berapa TODO di kode shop/ dan di file mana saja?",
        steps=[[("grep", {"pattern": "TODO", "path": "shop"})]],
        cm=[[("grep", {"pattern": "TODO", "path": "shop"})]],  # one call: codemode brings nothing, so it is not used
        final="3 TODO: shop/config.py, shop/cart.py, shop/report.py.",
        check=lambda repo, final: "3" in final and "config.py" in final,
        notes="kontrol: satu panggilan saja, codemode tidak dipakai",
    ),
    Task(
        id="rename-line-total",
        prompt="Ganti nama fungsi line_total menjadi item_total di seluruh repo, tes harus tetap hijau.",
        steps=[[("grep", {"pattern": "line_total"})],
               [("read_file", {"path": "shop/pricing.py"})],
               [("read_file", {"path": "shop/cart.py"})],
               [("read_file", {"path": "tests/test_pricing.py"})],
               [("edit_file", {"path": "shop/pricing.py", "old_string": "def line_total(item):",
                               "new_string": "def item_total(item):"})],
               [("edit_file", {"path": "shop/cart.py", "old_string": "from shop.pricing import apply_discount, line_total",
                               "new_string": "from shop.pricing import apply_discount, item_total"})],
               [("edit_file", {"path": "shop/cart.py", "old_string": "sum(line_total(i)",
                               "new_string": "sum(item_total(i)"})],
               [("edit_file", {"path": "tests/test_pricing.py", "old_string": "line_total", "new_string": "item_total",
                               "replace_all": True})],
               [("shell", {"command": f"{PYTEST} tests/test_pricing.py tests/test_cart.py"})]],
        cm=[_cm(f"""
hits = tools.grep(pattern='line_total')
files = sorted({{l.split(':', 1)[0] for l in hits.splitlines() if ':' in l}})
res = []
for f in files:
    res.append(f + ': ' + tools.edit_file(path=f, old_string='line_total', new_string='item_total', replace_all=True))
print('\\n'.join(res))
print(tools.shell(command={PYTEST!r} + ' tests/test_pricing.py tests/test_cart.py').strip().splitlines()[-1])
""")],
        final="line_total diganti item_total di shop/pricing.py, shop/cart.py dan tests/test_pricing.py; tes hijau.",
        check=lambda repo, final: tests_pass(repo, "tests/test_pricing.py tests/test_cart.py")
        and "line_total" not in (repo / "shop/cart.py").read_text(),
    ),
    Task(
        id="api-summary", kind="qna",
        prompt="Ringkas API publik (fungsi/kelas + argumen) dari shop/pricing.py, tax.py, cart.py, inventory.py.",
        steps=[[("read_file", {"path": "shop/pricing.py"})],
               [("read_file", {"path": "shop/tax.py"})],
               [("read_file", {"path": "shop/cart.py"})],
               [("read_file", {"path": "shop/inventory.py"})]],
        cm=[_cm("""
import ast
names = ['shop/pricing.py', 'shop/tax.py', 'shop/cart.py', 'shop/inventory.py']
srcs = tools.parallel([('read_file', {'path': n}) for n in names])
import re
for n, s in zip(names, srcs):
    code = '\\n'.join(re.sub(r'^\\s*\\d+[\\t|:] ?', '', l, count=1) for l in s.splitlines())
    try:
        tree = ast.parse(code)
    except SyntaxError:
        tree = ast.parse(open(n).read())
    out = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            out.append(f"{node.name}({', '.join(a.arg for a in node.args.args)})")
        elif isinstance(node, ast.ClassDef):
            meths = [f"{m.name}({', '.join(a.arg for a in m.args.args[1:])})" for m in node.body
                     if isinstance(m, ast.FunctionDef) and not m.name.startswith('_')]
            out.append(f"class {node.name}: " + ', '.join(meths))
    print(n + ': ' + '; '.join(out))
""")],
        final="pricing: apply_discount(total, code), unit_price(item), line_total(item); tax: add_tax(amount), "
              "tax_of(amount); cart: class Cart: add(name, price, qty), subtotal(), total(code); inventory: class "
              "Inventory: restock(name, qty), take(name, qty), low(limit).",
        check=lambda repo, final: all(s in final for s in ("apply_discount", "add_tax", "Cart", "Inventory")),
        notes="program mem-parse AST dan hanya mencetak signature",
    ),
    Task(
        id="fix-inventory-offbyone",
        prompt="test_inventory gagal. Cari penyebabnya, perbaiki, jalankan tes.",
        steps=[[("shell", {"command": f"{PYTEST} tests/test_inventory.py"})],
               [("read_file", {"path": "shop/inventory.py"})],
               [("read_file", {"path": "tests/test_inventory.py"})],
               [("edit_file", {"path": "shop/inventory.py", "old_string": INV_OLD, "new_string": INV_NEW})],
               [("shell", {"command": f"{PYTEST} tests/test_inventory.py"})]],
        cm=[_cm(f"""
run, src = tools.parallel([('shell', {{'command': {PYTEST!r} + ' tests/test_inventory.py'}}),
                           ('read_file', {{'path': 'shop/inventory.py'}})])
print('\\n'.join(l for l in run.splitlines() if 'FAILED' in l or 'Error' in l)[:1200])
print('\\n'.join(l for l in src.splitlines() if 'qty' in l))
"""), _cm(f"""
print(tools.edit_file(path='shop/inventory.py', old_string={INV_OLD!r}, new_string={INV_NEW!r}))
print(tools.shell(command={PYTEST!r} + ' tests/test_inventory.py').strip().splitlines()[-1])
""")],
        final="Inventory.take memakai qty > have + 1 (off-by-one); diganti qty > have. test_inventory hijau.",
        check=lambda repo, final: tests_pass(repo, "tests/test_inventory.py"),
    ),
    Task(
        id="qna-config-usage", kind="qna",
        prompt="Konstanta apa saja di shop/config.py dan di mana masing-masing dipakai?",
        steps=[[("read_file", {"path": "shop/config.py"})],
               [("grep", {"pattern": "TAX_RATE"})],
               [("grep", {"pattern": "MAX_ITEMS"})],
               [("grep", {"pattern": "DISCOUNT_CODES"})],
               [("grep", {"pattern": "CURRENCY"})]],
        cm=[_cm("""
names = ['TAX_RATE', 'CURRENCY', 'MAX_ITEMS', 'DISCOUNT_CODES']
res = tools.parallel([('grep', {'pattern': n}) for n in names])
for n, r in zip(names, res):
    users = sorted({l.split(':', 1)[0] for l in r.splitlines() if ':' in l and 'config.py' not in l})
    print(n, '->', ', '.join(users) or 'tidak dipakai')
""")],
        final="TAX_RATE -> shop/tax.py; CURRENCY -> tidak dipakai; MAX_ITEMS -> shop/cart.py; DISCOUNT_CODES -> "
              "shop/pricing.py.",
        check=lambda repo, final: "CURRENCY -> tidak dipakai" in final and "shop/tax.py" in final,
    ),
    Task(
        id="add-feature-low-stock-test",
        prompt="Tambahkan tes untuk Inventory.low() (default limit 3) lalu jalankan.",
        steps=[[("read_file", {"path": "shop/inventory.py"})],
               [("read_file", {"path": "tests/test_inventory.py"})],
               [("write_file", {"path": "tests/test_low.py", "content":
                   "from shop.inventory import Inventory\n\n\ndef test_low_default():\n    inv = Inventory()\n"
                   "    inv.restock('teh', 2); inv.restock('kopi', 9)\n    assert inv.low() == ['teh']\n"})],
               [("shell", {"command": f"{PYTEST} tests/test_low.py"})]],
        cm=[_cm(f"""
src = tools.read_file(path='shop/inventory.py')
print('\\n'.join(l for l in src.splitlines() if 'def low' in l or 'limit' in l))
print(tools.write_file(path='tests/test_low.py', content='''from shop.inventory import Inventory


def test_low_default():
    inv = Inventory()
    inv.restock('teh', 2); inv.restock('kopi', 9)
    assert inv.low() == ['teh']
'''))
print(tools.shell(command={PYTEST!r} + ' tests/test_low.py').strip().splitlines()[-1])
""")],
        final="tests/test_low.py ditambahkan (stok 2 masuk daftar low, 9 tidak); tes hijau.",
        check=lambda repo, final: (repo / "tests/test_low.py").exists() and tests_pass(repo, "tests/test_low.py"),
    ),
    Task(
        id="qna-failing-tests", kind="qna",
        prompt="Tes mana saja yang gagal sekarang dan apa penyebab singkatnya? Jangan ubah kode.",
        steps=[[("shell", {"command": f"{PYTEST} tests"})],
               [("read_file", {"path": "shop/tax.py"})],
               [("read_file", {"path": "shop/inventory.py"})]],
        cm=[_cm(f"""
run = tools.shell(command={PYTEST!r} + ' tests')
failed = [l for l in run.splitlines() if l.startswith('FAILED')]
print('\\n'.join(failed))
srcs = tools.parallel([('grep', {{'pattern': 'BUG', 'path': 'shop'}})])
print(srcs[0])
""")],
        final="Gagal: test_add_tax_rounds dan test_cart_total (add_tax memotong, bukan membulatkan) serta "
              "test_take_too_many (off-by-one di Inventory.take).",
        check=lambda repo, final: all(s in final for s in ("test_add_tax_rounds", "test_take_too_many")),
    ),
    Task(
        id="fix-both-and-verify",
        prompt="Perbaiki semua tes yang gagal di repo ini lalu jalankan seluruh tes.",
        steps=[[("shell", {"command": f"{PYTEST} tests"})],
               [("read_file", {"path": "shop/tax.py"})],
               [("read_file", {"path": "shop/inventory.py"})],
               [("read_file", {"path": "tests/test_tax.py"})],
               [("edit_file", {"path": "shop/tax.py", "old_string": TAX_FIX_OLD, "new_string": TAX_FIX_NEW})],
               [("edit_file", {"path": "shop/inventory.py", "old_string": INV_OLD, "new_string": INV_NEW})],
               [("shell", {"command": f"{PYTEST} tests"})]],
        cm=[_cm(f"""
run, tax, inv = tools.parallel([('shell', {{'command': {PYTEST!r} + ' tests'}}),
                                ('read_file', {{'path': 'shop/tax.py'}}),
                                ('read_file', {{'path': 'shop/inventory.py'}})])
print('\\n'.join(l for l in run.splitlines() if l.startswith('FAILED')))
print('\\n'.join(l for l in (tax + inv).splitlines() if 'BUG' in l))
"""), _cm(f"""
print(tools.edit_file(path='shop/tax.py', old_string={TAX_FIX_OLD!r}, new_string={TAX_FIX_NEW!r}))
print(tools.edit_file(path='shop/inventory.py', old_string={INV_OLD!r}, new_string={INV_NEW!r}))
print(tools.shell(command={PYTEST!r} + ' tests').strip().splitlines()[-1])
""")],
        final="Dua bug diperbaiki: add_tax kini round(), Inventory.take memakai qty > have. Seluruh tes hijau.",
        check=lambda repo, final: tests_pass(repo, "tests"),
    ),
]

BY_ID = {t.id: t for t in TASKS}
