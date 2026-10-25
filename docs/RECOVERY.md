# Recovering V/HOME

Your shared content lives in the cloud (Supabase project `kqmiuhnaeoshjynsttwa`). The TV only caches a copy.

## The TV shows "Pair this TV"
1. Read the 6-character code on the TV (it stays the same for 10 minutes, then refreshes).
2. On the phone open V/HOME, then **Displays**, and enter the code (or scan the QR).
3. Your content returns within a few seconds. Nothing is lost.

## The TV was reset or Developer Mode expired
See `docs/DEV-MODE.md`, then pair again as above.

## Roll back the TV app
Keep the previous `.ipk` from `build/` and run `node_modules/.bin/ares-install --device tv <file.ipk>` (upgrade in place).

## Export and import
Phone, **Settings**, **Backup**: Export household downloads one JSON file. Import adds those items to the current household with new IDs. Photos are not included yet.

## Change or rotate the database password
Supabase dashboard, Project Settings, Database, Reset database password. Then run `supabase link --project-ref kqmiuhnaeoshjynsttwa` again on the Mac when it asks.

## The free Supabase project paused (about 7 days of no use)
Open the Supabase dashboard and press **Restore project**. The TV keeps showing its last saved content while paused, with a "Showing saved content" note.

## A partner lost their phone or password
Sign in on a new phone. If the password is lost, use Supabase dashboard, Authentication, Users, and send a password reset.

## VNode: the node is unreachable
The app says "Can't reach the node" or "Not on Wi-Fi". First check you are on the home Wi-Fi and not on a guest network or VPN. Then check the Pi has power and its green light is on. Try `ssh vnode@vnode.local`, or use its IP from the router. If it answers, run `./vnode/deploy.sh status` and `./vnode/deploy.sh diag`. If the service is down, restart it from the app (Restart V/HOME service) or on the Pi with `sudo systemctl restart vhome-vnode`. If the Pi is dead, unplug and replug the power. While it is down, Home on the TV goes to LG as usual. To use the phone as the watcher meanwhile, see "Use this phone instead" in [VNODE.md](VNODE.md); confirm the node is unplugged first.

## VNode: TV certificate mismatch
The node refuses a TV whose certificate differs from the pinned one. It never trusts it. If the TV was really reset or updated, open the app's node screen, tick "TV was reset (re-pin)", and pair the TV again, accepting the prompt on the TV. If you did not reset the TV, do not re-pin; find out what else is at that address.

## VNode: TV pairing required
Open the app, "Pair the TV through the node", enter the TV's IP address, tap Pair TV, and accept the prompt on the TV within 60 seconds.

## VNode: lost phone
On the Pi run `vnode phones list`, then `vnode phones revoke ID` for that phone. Or revoke it from another paired phone in the app. A revoked phone cannot control the node.

## VNode: restore a node backup
Backups are made with `./vnode/deploy.sh backup` and hold secrets, so keep them private. Restore steps are in the backup and restore section of [VNODE.md](VNODE.md). After a good restore the node id is the same and phones stay paired.

## VNode: the SD card died
1. Flash a new card as in [VNODE.md](VNODE.md): same hostname `vnode`, same user.
2. Run `./vnode/deploy.sh install`.
3. If you have a backup, restore it (see above). The node id, the TV pairing and the phone pairings come back.
4. If you have no backup, the install makes a new certificate and so a new node id. Every phone must forget the node and pair again, and the TV must be paired through the node again. The Mac's `known_hosts` may also complain about the new Pi; remove the old `vnode.local` line with `ssh-keygen -R vnode.local`.

