"""Commands for the reference library — one module per job:

add.py      db-add                  put a new paper in
edit.py     db-edit, db-delete      change or remove a paper
browse.py   db-list, db-search      look at what is there
health.py   db-check, db-rebuild    find and repair problems
backup.py   db-export, db-import    move the library in and out
"""

from larklab.cli.library.add import add_paper
from larklab.cli.library.backup import export_papers, import_papers
from larklab.cli.library.browse import list_papers, search_paper
from larklab.cli.library.edit import delete_paper, edit_paper
from larklab.cli.library.health import check_papers, rebuild_embeddings

LIBRARY_COMMANDS = (
    add_paper,
    edit_paper,
    delete_paper,
    list_papers,
    search_paper,
    check_papers,
    rebuild_embeddings,
    export_papers,
    import_papers,
)
