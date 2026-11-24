# Sessions

`Session.objects.get_or_fetch("00123")` renvoie la session existante ou la
cree en base avec les informations fournies par le manager.

La methode `SessionManager._fetch_session_data(session_number)` recupere la page
`https://formations.protection-civile.org/detail-formation/` avec le parametre
`id_session`. Elle renvoie un tuple contenant l'adresse et la premiere date
de formation affichee. La requete utilise un timeout de 10 secondes.
Les sessions deja presentes ne sont pas modifiees.

En mode `DEBUG` uniquement, HelloAsso et la recuperation des sessions utilisent
l'adaptateur TLS partage de `main.utils`. Il relache le controle X.509 strict
sans desactiver la verification des certificats ni du nom d'hote.

Le conteneur de developpement utilise les autorites de certification de l'hote.
Par defaut, il monte `/etc/ssl/certs/ca-certificates.crt` en lecture seule ;
definir `DEV_CA_BUNDLE` pour utiliser un autre fichier de certificats PEM.

Si la recuperation echoue avec une erreur HTTP, reseau ou de contenu, l'echec est
journalise et la session est tout de meme renvoyee et conservee en base,
sans adresse ni date. Les appels suivants reutilisent cette session sans
nouvelle tentative de recuperation.

Appliquer les migrations avec `python manage.py migrate` avant utilisation.
