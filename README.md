# vibe-trader

pull vibe-trading main:
```pip install --force-reinstall --no-cache-dir git+https://github.com/HKUDS/Vibe-Trading.git@main```


Dependencies:
```pipreqs . --force```


vibe-trading connector check 
vibe-trading connector authorize robinhood-live-mcp

vibe-trading run -p "Use account 12345 and explicitly invoke the get_equity_positions tool to show my holdings" --max-iter 5