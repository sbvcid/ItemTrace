"""ItemTrace 的測試套件。

需要這個 __init__.py：沒有它的話 `tests/` 只是 namespace package，
Python 會沿著 sys.path 往後掃描，一旦 site-packages 裡有同名 `tests`
套件（真的會有），那個就會贏，`from tests.conftest import ...` 會拿到
別的模組而不是本地這個。建成 regular package 後依 sys.path 順序，
本地的一定先被找到。
"""