"""Run in an MCP Console Python cell after configuring the browser.

On macOS, set CHROME_PATH to chrome-headless-shell, NOKAP_TRANSPORT to pipe,
and NOKAP_CHROME_ARGS to '["--single-process"]'. Requires great-tables,
pandas, matplotlib, and this version of nokap in the Console environment.
"""

import matplotlib.pyplot as plt
import pandas as pd
from great_tables import GT

import nokap

table = (
    GT(
        pd.DataFrame(
            {
                "Region": ["North", "South", "East", "West"],
                "Revenue": [18240, 15750, 21100, 16980],
                "Growth": [0.12, 0.08, 0.19, 0.10],
            }
        )
    )
    .tab_header(
        title="Quarterly sales",
        subtitle="Rendered inside the MCP Console sandbox",
    )
    .fmt_currency(columns="Revenue")
    .fmt_percent(columns="Growth")
)

try:
    table.gtsave("table.png")
finally:
    nokap.close()

# Console returns pyplot figures as MCP images. Preserve the table's pixels.
pixels = plt.imread("table.png")
height, width = pixels.shape[:2]
figure = plt.figure(figsize=(width / 100, height / 100), dpi=100)
figure.figimage(pixels)
plt.show()
