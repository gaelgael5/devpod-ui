# 027 — MCP : injection LogQL par interpolation non échappée

- **Sévérité** : mineur (pas d'élévation de privilège : `query` brut déjà exposé, logs non cloisonnés)
- **Sous-système** : mcp / logs
- **Fichier** : `mcp/devpod_tools/logs_tools.py:53, 61`
- **Statut** : ouvert

**Symptôme** :
```python
sel = [f'{lbl}="{getattr(p, key)}"' for key, lbl in _LABEL.items() if getattr(p, key)]
...
expr += f' | json | level="{p.level}"'
```
Une valeur de filtre (`host`, `role`, `level`…) contenant un `"` casse le matcher et injecte du LogQL
arbitraire → requêtes malformées, comportement imprévisible. Pas d'élévation de privilège (le
paramètre `query` expose déjà du LogQL brut au même appelant).

**Correction** : échapper les guillemets/backslashes des valeurs interpolées.
