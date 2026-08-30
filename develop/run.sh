cd ~/Projects/filetranscode
source .venv/bin/activate
for plugin in develop/plugins/*/; do
    pip install -qe "$plugin"
done
python3 develop/run_demo.py
