[README.md](https://github.com/user-attachments/files/35412681/README.md)
# Bot-conciliateur-new# Alerte SMS conciliateur de justice (Paris 1er à 20e)

Vérifie toutes les 5 minutes (7h à 23h) la page RDV DAJ et envoie un SMS avec le jour, l'heure, le lieu et le lien dès qu'un créneau apparaît dans Paris intra muros. Un même créneau n'est signalé qu'une fois.

## Installation (gratuit)

1. Crée un dépôt **public** sur GitHub. Public = minutes illimitées et gratuites. Le dépôt ne contient que le code et des infos déjà publiques ; tes identifiants SMS vont dans les secrets, chiffrés et jamais affichés.
2. Dépose `bot.py`, `README.md` et le dossier caché `.github` (Add file > Upload files).
3. Secrets (Settings > Secrets and variables > Actions > New repository secret) :
   * **Free Mobile** (gratuit, aucun numéro à saisir) : active « Notifications par SMS » dans ton Espace abonné, puis crée `FREE_USER` (identifiant abonné) et `FREE_PASS` (clé fournie).
   * **Autre opérateur (Twilio)** : `TWILIO_SID`, `TWILIO_TOKEN`, `TWILIO_FROM`, `SMS_TO` (+336...).
4. Onglet Actions > Surveillance conciliateur > Run workflow, coche **Envoyer un SMS de test**. Tu dois recevoir un SMS en moins d'une minute.

## À savoir

* GitHub peut retarder les passages de quelques minutes aux heures chargées.
* `historique.csv` note quand chaque créneau a été détecté. Après quelques publications, tu sauras à quels jours et heures la Ville ouvre les créneaux.
* Au premier créneau trouvé, la page est enregistrée dans `snapshots/`. Si le SMS affiche « jour ? » ou « lieu ? », ce fichier permet d'ajuster le parseur.
* GitHub met en pause les tâches planifiées d'un dépôt public sans activité pendant 60 jours : relance avec « Enable workflow » si besoin.
* Rendez-vous obtenu ? Actions > Surveillance conciliateur > « … » > Disable workflow.
