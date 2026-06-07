# LESSONS

- [scripts] `IFS=$'\n\t'` en tête de script casse l'expansion non-quotée d'une chaîne d'options (ex. `ssh $SSH_OPTS`) : pas de découpage sur espaces → tout passe en un seul argument. Utiliser un tableau bash (`SSH_OPTS=(-o A -o B)` puis `"${SSH_OPTS[@]}"`).
- [debug] Ne jamais masquer stderr (`2>/dev/null`) sur une commande qui échoue en boucle : capturer la sortie (`LAST_ERR=$(cmd 2>&1)`) et l'afficher. Une ligne d'erreur réelle vaut mieux que quatre théories. Capturer le stderr AU PREMIER échec, pas après plusieurs hypothèses.
