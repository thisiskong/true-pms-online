
uv run python export_schema.py --host dv01 --port 5432 --dbname pmsonline --user pmsonline --password pmsonline --output dev
uv run python export_schema.py --host db01 --port 5432 --dbname pmsonline --user pmsonline --password pmsonline#2022 --output prd

# create diff
# uv run python diff_schema.py --source dev --target prd --output delta

