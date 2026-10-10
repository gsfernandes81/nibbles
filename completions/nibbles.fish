# Completions for nibbles, the one command (ytq and dlq until 2026-10-10).
#
# Install as a symlink, so that pulling the repo updates them:
#
#   ln -s ~/nibbles/completions/nibbles.fish ~/.config/fish/completions/
#
# The symlink points into the checkout rather than copying, for the same reason
# every path in expire_sched.py does: the checkout is the one queue there is,
# and a copy of anything here goes stale without saying so.

function __nibbles_bare -d "nothing but the command typed yet"
    test (count (commandline -opc)) -le 1
end

function __nibbles_after -d "the subcommand already typed is one of these"
    set -l tokens (commandline -opc)
    test (count $tokens) -ge 2; or return 1
    contains -- $tokens[2] $argv
end

# No file completion by default: few of these take a path, and offering the
# whole of the home directory in place of a download name is worse than
# offering nothing. --from-json and the directories ask for their own.
complete -c nibbles -f

# The app, on a tab. A bare `nibbles` opens Search.
complete -c nibbles -n __nibbles_bare -a search   -d "search YouTube for the words after it (~0.1 MB)"
complete -c nibbles -n __nibbles_bare -a subs     -d "your subscription feed (needs the yt-dlp cookies)"
complete -c nibbles -n __nibbles_bare -a wl       -d "your Watch Later (needs the yt-dlp cookies)"
complete -c nibbles -n __nibbles_bare -a queue    -d "the queue: reorder, rename, remove, retry, download now"
complete -c nibbles -n __nibbles_bare -a more     -d "the settings, destinations and nightly job"

# The commands that answer without the app.
complete -c nibbles -n __nibbles_bare -a file     -d "queue a direct file download from a URL"
complete -c nibbles -n __nibbles_bare -a status   -d "queue, budget, window times and job state"
complete -c nibbles -n __nibbles_bare -a list     -d "every download, and how much of it is here"
complete -c nibbles -n __nibbles_bare -a path     -d "where a finished download landed"
complete -c nibbles -n __nibbles_bare -a dest     -d "show or set where finished downloads are put"
complete -c nibbles -n __nibbles_bare -a settings -d "the window, the reserve, the budget and what is said"
complete -c nibbles -n __nibbles_bare -a files    -d "just the queued item files"
complete -c nibbles -n __nibbles_bare -a logs     -d "last 40 lines of the runner log"
complete -c nibbles -n __nibbles_bare -a dump     -d "everything a bug report needs, in one paste"
complete -c nibbles -n __nibbles_bare -a run-now  -d "fire the whole queue once, without waiting"
complete -c nibbles -n __nibbles_bare -a arm      -d "register the nightly job"
complete -c nibbles -n __nibbles_bare -a cancel   -d "unregister it"
complete -c nibbles -n __nibbles_bare -a help     -d "every command"

# A video URL as the first word, or the YouTube flags anywhere.
complete -c nibbles -l now -d "start it in the background instead of waiting for the window (spends data)"
complete -c nibbles -l list -d "print the formats and caps (or subs, wl), write nothing"
complete -c nibbles -l from-json -r -F -d "reuse a saved 'yt-dlp -J' dump or search; costs no data"
complete -c nibbles -n "not __nibbles_after file" -l dest -r -F \
    -d "put this one somewhere other than the configured video directory"
complete -c nibbles -n "__nibbles_after --list" -a "subs wl"

# `nibbles file URL` queues a direct file download; these flags apply only
# after `file`, so they never crowd the verb list.
complete -c nibbles -n "__nibbles_after file" -l name -r -d "saved file name (default: taken from the URL)"
complete -c nibbles -n "__nibbles_after file" -l number -r -d "queue priority prefix (default: after the last)"
complete -c nibbles -n "__nibbles_after file" -l sha256 -r -d "verify the finished file before delivery"
complete -c nibbles -n "__nibbles_after file" -l expect-bytes -r -d "spending cap when the server states no size"
complete -c nibbles -n "__nibbles_after file" -l dest -r -d "put this one somewhere else"
complete -c nibbles -n "__nibbles_after file" -l probe -d "print the size and resume support, write nothing"
complete -c nibbles -n "__nibbles_after file" -l dry-run -d "print the item instead of writing it"
complete -c nibbles -n "__nibbles_after file" -l again -d "queue it even though it is already queued or done"

# `nibbles names` prints `name<TAB>state`, which is fish's own format for a
# candidate with a description, so the state shows up beside each name in the
# picker. It walks the queue directories and parses no item headers, because
# this runs on every press of the tab key.
complete -c nibbles -n "__nibbles_after path dump" -a "(nibbles names 2>/dev/null)"

# `dest` takes a kind and then a directory. Directories only — the destination
# is a folder, and offering files here would only ever be a mis-tap.
complete -c nibbles -n "__nibbles_after dest; and test (count (commandline -opc)) -eq 2" \
    -a video -d "where finished videos go"
complete -c nibbles -n "__nibbles_after dest; and test (count (commandline -opc)) -eq 2" \
    -a audio -d "where audio-only downloads go"
complete -c nibbles -n "__nibbles_after dest; and test (count (commandline -opc)) -eq 2" \
    -a file -d "where direct file downloads go"
complete -c nibbles -n "__nibbles_after dest; and test (count (commandline -opc)) -ge 3" \
    -a default -d "put the built-in default back"
complete -c nibbles -n "__nibbles_after dest; and test (count (commandline -opc)) -ge 3" \
    -a "(__fish_complete_directories)"

# `settings` takes a name and then a value. The names are spelled out here
# rather than read from the runner: a completion may not import anything or
# run a command that could, because this fires on every press of the tab key —
# `nibbles names` is the one exception and it only walks directories.
function __nibbles_setting -d "the setting is one of these, and its value is next"
    set -l tokens (commandline -opc)
    test (count $tokens) -eq 3; or return 1
    test $tokens[2] = settings; or return 1
    contains -- $tokens[3] $argv
end

function __nibbles_setting_name -d "a setting's name comes next"
    __nibbles_after settings; and test (count (commandline -opc)) -eq 2
end

complete -c nibbles -n __nibbles_setting_name -a window -d "how early downloads may start (a multiple of 15 minutes)"
complete -c nibbles -n __nibbles_setting_name -a reserve -d "data kept back, never spent (MB)"
complete -c nibbles -n __nibbles_setting_name -a reserve-when-paid -d "keep it when paid data is there"
complete -c nibbles -n __nibbles_setting_name -a paid-min -d "paid data needed to waive it (MB; 0 is any at all)"
complete -c nibbles -n __nibbles_setting_name -a budget -d "where the figure to spend comes from"
complete -c nibbles -n __nibbles_setting_name -a allowance -d "the manual budget's daily allowance (MB or GB)"
complete -c nibbles -n __nibbles_setting_name -a reset -d "when the manual budget's day starts again (phone time)"
complete -c nibbles -n __nibbles_setting_name -a auto -d "let the nightly job download"
complete -c nibbles -n __nibbles_setting_name -a notify-blocked -d "say when a firing is blocked"
complete -c nibbles -n "__nibbles_after settings; and test (count (commandline -opc)) -eq 3" \
    -a default -d "put the built-in default back"
complete -c nibbles -n "__nibbles_setting auto" -a on -d "the nightly job downloads"
complete -c nibbles -n "__nibbles_setting auto" -a off \
    -d "the nightly job fires and does nothing; run-now still works"
complete -c nibbles -n "__nibbles_setting reserve-when-paid" -a yes \
    -d "the reserve is kept even when paid data is there"
complete -c nibbles -n "__nibbles_setting reserve-when-paid" -a no \
    -d "paid data waives the reserve"
complete -c nibbles -n "__nibbles_setting budget" -a zwana -d "the portal's reading"
complete -c nibbles -n "__nibbles_setting budget" -a manual -d "a daily allowance you set"
complete -c nibbles -n "__nibbles_setting notify-blocked" -a on \
    -d "a firing stopped by a fault says so on the phone"
complete -c nibbles -n "__nibbles_setting notify-blocked" -a off \
    -d "a blocked firing is in the log only; a failed item still says so"

complete -c nibbles -n "__nibbles_after run-now" -l blind \
    -d "no portal reachable: spend mobile data (asks first)"
complete -c nibbles -n "__nibbles_after run-now" -l yes \
    -d "do not ask before spending data"
