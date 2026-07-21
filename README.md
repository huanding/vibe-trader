# vibe-trader

## Vibe Trading dependency for auth
pull vibe-trading main:
```pip install --force-reinstall --no-cache-dir git+https://github.com/HKUDS/Vibe-Trading.git@main```


vibe-trading connector check 
vibe-trading connector authorize robinhood-live-mcp

vibe-trading run -p "Use account $ROBINHOOD_ACCOUNT_NUMBER and explicitly invoke the get_equity_positions tool to show my holdings" --max-iter 5

## PIP Dependencies
```pipreqs . --force```

## Check Syntax
```pip install ruff```
```ruff check .```
```ruff check --fix .```

## venv
```source env/bin/activate```