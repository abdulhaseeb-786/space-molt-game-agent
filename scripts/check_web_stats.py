import requests

for pilot in ('AI26-G113-A', 'AI26-G113-B'):
    r = requests.get(f'https://spacemolt.com/player/{pilot}', headers={'User-Agent': 'Mozilla/5.0'})
    print(f'=== {pilot} ===')
    tiles = r.text.split('statTile')
    for tile in tiles[1:]:
        if 'statValue' in tile and 'statName' in tile:
            try:
                val = tile.split('statValue">')[1].split('</span>')[0]
                name = tile.split('statName">')[1].split('</span>')[0]
                if name in ('Credits Earned', 'Ore Mined', 'Trades Completed', 'Distance Traveled', 'Systems Explored'):
                    print(f'  {name}: {val}')
            except Exception:
                pass
