"""Op handlers — one function per Plan op kind.

Each handler receives the typed Op and the SpreadsheetContext, performs
its work against pandas, writes its output to the register, and returns
an `OpResult` for the trace.
"""

from app.spreadsheet.ops.aggregate import handle_aggregate, handle_group_by
from app.spreadsheet.ops.derive import handle_add_column
from app.spreadsheet.ops.join import handle_join
from app.spreadsheet.ops.load import handle_load_csv, handle_load_excel
from app.spreadsheet.ops.output import handle_to_chart, handle_to_table
from app.spreadsheet.ops.reshape import handle_melt, handle_pivot
from app.spreadsheet.ops.select import handle_filter_rows, handle_select_columns
from app.spreadsheet.ops.sort import handle_head, handle_sort, handle_tail

# Registry: kind → handler. Executor uses this to dispatch.
HANDLERS = {
    "load_csv": handle_load_csv,
    "load_excel": handle_load_excel,
    "select_columns": handle_select_columns,
    "filter_rows": handle_filter_rows,
    "add_column": handle_add_column,
    "group_by": handle_group_by,
    "aggregate": handle_aggregate,
    "sort": handle_sort,
    "head": handle_head,
    "tail": handle_tail,
    "join": handle_join,
    "pivot": handle_pivot,
    "melt": handle_melt,
    "to_table": handle_to_table,
    "to_chart": handle_to_chart,
}

__all__ = ["HANDLERS"]
