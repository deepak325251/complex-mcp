#!/bin/zsh

_ROOT="$(cd "$(dirname "$0")" && pwd)"

# Apps now import `software.utils.*` (seedless world.pkl fixtures). `fastmcp run`
# only puts the app's own dir on sys.path, so make the repo root importable or
# LightSystem (and others) die with "No module named 'software'".
export PYTHONPATH="${_ROOT}:${PYTHONPATH}"

# Use the project venv's binaries (fastmcp, python) without requiring the caller
# to `source .venv/bin/activate` first -- otherwise every server dies with
# "command not found: fastmcp" and the "started (PID ...)" lines lie.
if [ -x "${_ROOT}/.venv/bin/fastmcp" ]; then
    export PATH="${_ROOT}/.venv/bin:${PATH}"
fi
if ! command -v fastmcp >/dev/null 2>&1; then
    echo "ERROR: 'fastmcp' not found. Create the venv (python -m venv .venv && .venv/bin/pip install -r requirements.txt) or activate it." >&2
    exit 1
fi

# World seed for every app (rolled at login). Override by exporting COMPLEXMCP_SEED
# before running. Children inherit it.
export COMPLEXMCP_SEED="${COMPLEXMCP_SEED:-42}"
echo "[start_softwares] fastmcp=$(command -v fastmcp)  COMPLEXMCP_SEED=${COMPLEXMCP_SEED}${COMPLEXMCP_FIXTURE:+  COMPLEXMCP_FIXTURE=$COMPLEXMCP_FIXTURE}"

# Signal handler function
cleanup() {
    echo -e "\nReceived interrupt signal, shutting down all child processes..."
    
    # Send SIGTERM to all child processes
    for PID in "${PIDS[@]}"; do
        if kill -0 $PID 2>/dev/null; then
            echo "Shutting down process $PID"
            kill $PID
        fi
    done
    
    # Wait for all processes to finish
    wait
    echo "All processes have been terminated"
    exit 0
}

# Set up signal traps
trap cleanup INT TERM

# Array to store process IDs
PIDS=()

echo "Starting Light application suite..."

# Start each application
fastmcp run software/LightSystem/app.py --transport http --host 0.0.0.0 --port 9000 &
PIDS+=($!)
echo "LightSystem started (PID: $!, Port: 9000)"
sleep 1

fastmcp run software/LightTalk/app.py --transport http --host 0.0.0.0 --port 9001 &
PIDS+=($!)
echo "LightTalk started (PID: $!, Port: 9001)"
sleep 1

fastmcp run software/LightShop/app.py --transport http --host 0.0.0.0 --port 9002 &
PIDS+=($!)
echo "LightShop started (PID: $!, Port: 9002)"
sleep 1

fastmcp run software/LightWeather/app.py --transport http --host 0.0.0.0 --port 9003 &
PIDS+=($!)
echo "LightWeather started (PID: $!, Port: 9003)"
sleep 1

fastmcp run software/LightFlight/app.py --transport http --host 0.0.0.0 --port 9004 &
PIDS+=($!)
echo "LightFlight started (PID: $!, Port: 9004)"
sleep 1

fastmcp run software/LightStock/app.py --transport http --host 0.0.0.0 --port 9005 &
PIDS+=($!)
echo "LightStock started (PID: $!, Port: 9005)"
sleep 1

fastmcp run software/LightNews/app.py --transport http --host 0.0.0.0 --port 9006 &
PIDS+=($!)
echo "LightNews started (PID: $!, Port 9006)"
sleep 1

fastmcp run software/LightMail/app.py --transport http --host 0.0.0.0 --port 9007 &
PIDS+=($!)
echo "LightMail started (PID: $!, Port: 9007)"
sleep 1

fastmcp run software/LightCalendar/app.py --transport http --host 0.0.0.0 --port 9008 &
PIDS+=($!)
echo "LightCalendar started (PID: $!, Port: 9008)"
sleep 1

fastmcp run software/LightTasks/app.py --transport http --host 0.0.0.0 --port 9014 &
PIDS+=($!)
echo "LightTasks started (PID: $!, Port: 9014)"
sleep 1






































































































fastmcp run software/LightNotes/app.py --transport http --host 0.0.0.0 --port 9015 &
PIDS+=($!)
echo "LightNotes started (PID: $!, Port: 9015)"
sleep 1

fastmcp run software/LightMeet/app.py --transport http --host 0.0.0.0 --port 9016 &
PIDS+=($!)
echo "LightMeet started (PID: $!, Port: 9016)"
sleep 1

fastmcp run software/LightCRM/app.py --transport http --host 0.0.0.0 --port 9017 &
PIDS+=($!)
echo "LightCRM started (PID: $!, Port: 9017)"
sleep 1

fastmcp run software/LightHR/app.py --transport http --host 0.0.0.0 --port 9018 &
PIDS+=($!)
echo "LightHR started (PID: $!, Port: 9018)"
sleep 1

fastmcp run software/LightIssues/app.py --transport http --host 0.0.0.0 --port 9019 &
PIDS+=($!)
echo "LightIssues started (PID: $!, Port: 9019)"
sleep 1

fastmcp run software/LightBudget/app.py --transport http --host 0.0.0.0 --port 9020 &
PIDS+=($!)
echo "LightBudget started (PID: $!, Port: 9020)"
sleep 1

fastmcp run software/LightWallet/app.py --transport http --host 0.0.0.0 --port 9021 &
PIDS+=($!)
echo "LightWallet started (PID: $!, Port: 9021)"
sleep 1

fastmcp run software/LightTax/app.py --transport http --host 0.0.0.0 --port 9022 &
PIDS+=($!)
echo "LightTax started (PID: $!, Port: 9022)"
sleep 1

fastmcp run software/LightAuction/app.py --transport http --host 0.0.0.0 --port 9023 &
PIDS+=($!)
echo "LightAuction started (PID: $!, Port: 9023)"
sleep 1

fastmcp run software/LightSubscription/app.py --transport http --host 0.0.0.0 --port 9024 &
PIDS+=($!)
echo "LightSubscription started (PID: $!, Port: 9024)"
sleep 1

fastmcp run software/LightRide/app.py --transport http --host 0.0.0.0 --port 9025 &
PIDS+=($!)
echo "LightRide started (PID: $!, Port: 9025)"
sleep 1

fastmcp run software/LightHotel/app.py --transport http --host 0.0.0.0 --port 9026 &
PIDS+=($!)
echo "LightHotel started (PID: $!, Port: 9026)"
sleep 1

fastmcp run software/LightRental/app.py --transport http --host 0.0.0.0 --port 9027 &
PIDS+=($!)
echo "LightRental started (PID: $!, Port: 9027)"
sleep 1

fastmcp run software/LightFood/app.py --transport http --host 0.0.0.0 --port 9028 &
PIDS+=($!)
echo "LightFood started (PID: $!, Port: 9028)"
sleep 1

fastmcp run software/LightVideo/app.py --transport http --host 0.0.0.0 --port 9029 &
PIDS+=($!)
echo "LightVideo started (PID: $!, Port: 9029)"
sleep 1

fastmcp run software/LightPodcast/app.py --transport http --host 0.0.0.0 --port 9030 &
PIDS+=($!)
echo "LightPodcast started (PID: $!, Port: 9030)"
sleep 1

fastmcp run software/LightPhoto/app.py --transport http --host 0.0.0.0 --port 9031 &
PIDS+=($!)
echo "LightPhoto started (PID: $!, Port: 9031)"
sleep 1

fastmcp run software/LightRead/app.py --transport http --host 0.0.0.0 --port 9032 &
PIDS+=($!)
echo "LightRead started (PID: $!, Port: 9032)"
sleep 1

fastmcp run software/LightForum/app.py --transport http --host 0.0.0.0 --port 9033 &
PIDS+=($!)
echo "LightForum started (PID: $!, Port: 9033)"
sleep 1

fastmcp run software/LightHome/app.py --transport http --host 0.0.0.0 --port 9034 &
PIDS+=($!)
echo "LightHome started (PID: $!, Port: 9034)"
sleep 1

fastmcp run software/LightSecurity/app.py --transport http --host 0.0.0.0 --port 9035 &
PIDS+=($!)
echo "LightSecurity started (PID: $!, Port: 9035)"
sleep 1

fastmcp run software/LightEnergy/app.py --transport http --host 0.0.0.0 --port 9036 &
PIDS+=($!)
echo "LightEnergy started (PID: $!, Port: 9036)"
sleep 1

fastmcp run software/LightFitness/app.py --transport http --host 0.0.0.0 --port 9037 &
PIDS+=($!)
echo "LightFitness started (PID: $!, Port: 9037)"
sleep 1

fastmcp run software/LightMed/app.py --transport http --host 0.0.0.0 --port 9038 &
PIDS+=($!)
echo "LightMed started (PID: $!, Port: 9038)"
sleep 1

fastmcp run software/LightLearn/app.py --transport http --host 0.0.0.0 --port 9039 &
PIDS+=($!)
echo "LightLearn started (PID: $!, Port: 9039)"
sleep 1

fastmcp run software/LightVault/app.py --transport http --host 0.0.0.0 --port 9040 &
PIDS+=($!)
echo "LightVault started (PID: $!, Port: 9040)"
sleep 1

fastmcp run software/LightDrive/app.py --transport http --host 0.0.0.0 --port 9041 &
PIDS+=($!)
echo "LightDrive started (PID: $!, Port: 9041)"
sleep 1

fastmcp run software/LightSign/app.py --transport http --host 0.0.0.0 --port 9042 &
PIDS+=($!)
echo "LightSign started (PID: $!, Port: 9042)"
sleep 1

fastmcp run software/LightGame/app.py --transport http --host 0.0.0.0 --port 9043 &
PIDS+=($!)
echo "LightGame started (PID: $!, Port: 9043)"
sleep 1

fastmcp run software/LightActiveCampaign/app.py --transport http --host 0.0.0.0 --port 9044 &
PIDS+=($!)
echo "LightActiveCampaign started (PID: $!, Port: 9044)"
sleep 1
fastmcp run software/LightAirbnb/app.py --transport http --host 0.0.0.0 --port 9045 &
PIDS+=($!)
echo "LightAirbnb started (PID: $!, Port: 9045)"
sleep 1
fastmcp run software/LightAirtable/app.py --transport http --host 0.0.0.0 --port 9046 &
PIDS+=($!)
echo "LightAirtable started (PID: $!, Port: 9046)"
sleep 1
fastmcp run software/LightAlgolia/app.py --transport http --host 0.0.0.0 --port 9047 &
PIDS+=($!)
echo "LightAlgolia started (PID: $!, Port: 9047)"
sleep 1
fastmcp run software/LightAlpaca/app.py --transport http --host 0.0.0.0 --port 9048 &
PIDS+=($!)
echo "LightAlpaca started (PID: $!, Port: 9048)"
sleep 1
fastmcp run software/LightAmadeus/app.py --transport http --host 0.0.0.0 --port 9049 &
PIDS+=($!)
echo "LightAmadeus started (PID: $!, Port: 9049)"
sleep 1
fastmcp run software/LightAmazonSeller/app.py --transport http --host 0.0.0.0 --port 9050 &
PIDS+=($!)
echo "LightAmazonSeller started (PID: $!, Port: 9050)"
sleep 1
fastmcp run software/LightAmplitude/app.py --transport http --host 0.0.0.0 --port 9051 &
PIDS+=($!)
echo "LightAmplitude started (PID: $!, Port: 9051)"
sleep 1
fastmcp run software/LightAsana/app.py --transport http --host 0.0.0.0 --port 9052 &
PIDS+=($!)
echo "LightAsana started (PID: $!, Port: 9052)"
sleep 1
fastmcp run software/LightBambooHR/app.py --transport http --host 0.0.0.0 --port 9053 &
PIDS+=($!)
echo "LightBambooHR started (PID: $!, Port: 9053)"
sleep 1
fastmcp run software/LightBigCommerce/app.py --transport http --host 0.0.0.0 --port 9054 &
PIDS+=($!)
echo "LightBigCommerce started (PID: $!, Port: 9054)"
sleep 1
fastmcp run software/LightBinance/app.py --transport http --host 0.0.0.0 --port 9055 &
PIDS+=($!)
echo "LightBinance started (PID: $!, Port: 9055)"
sleep 1
fastmcp run software/LightBox/app.py --transport http --host 0.0.0.0 --port 9056 &
PIDS+=($!)
echo "LightBox started (PID: $!, Port: 9056)"
sleep 1
fastmcp run software/LightCalendly/app.py --transport http --host 0.0.0.0 --port 9057 &
PIDS+=($!)
echo "LightCalendly started (PID: $!, Port: 9057)"
sleep 1
fastmcp run software/LightCloudflare/app.py --transport http --host 0.0.0.0 --port 9058 &
PIDS+=($!)
echo "LightCloudflare started (PID: $!, Port: 9058)"
sleep 1
fastmcp run software/LightCoinbase/app.py --transport http --host 0.0.0.0 --port 9059 &
PIDS+=($!)
echo "LightCoinbase started (PID: $!, Port: 9059)"
sleep 1
fastmcp run software/LightConfluence/app.py --transport http --host 0.0.0.0 --port 9060 &
PIDS+=($!)
echo "LightConfluence started (PID: $!, Port: 9060)"
sleep 1
fastmcp run software/LightContentful/app.py --transport http --host 0.0.0.0 --port 9061 &
PIDS+=($!)
echo "LightContentful started (PID: $!, Port: 9061)"
sleep 1
fastmcp run software/LightDatadog/app.py --transport http --host 0.0.0.0 --port 9062 &
PIDS+=($!)
echo "LightDatadog started (PID: $!, Port: 9062)"
sleep 1
fastmcp run software/LightDiscord/app.py --transport http --host 0.0.0.0 --port 9063 &
PIDS+=($!)
echo "LightDiscord started (PID: $!, Port: 9063)"
sleep 1
fastmcp run software/LightDocuSign/app.py --transport http --host 0.0.0.0 --port 9064 &
PIDS+=($!)
echo "LightDocuSign started (PID: $!, Port: 9064)"
sleep 1
fastmcp run software/LightDoorDash/app.py --transport http --host 0.0.0.0 --port 9065 &
PIDS+=($!)
echo "LightDoorDash started (PID: $!, Port: 9065)"
sleep 1
fastmcp run software/LightDropbox/app.py --transport http --host 0.0.0.0 --port 9066 &
PIDS+=($!)
echo "LightDropbox started (PID: $!, Port: 9066)"
sleep 1
fastmcp run software/LightEtsy/app.py --transport http --host 0.0.0.0 --port 9067 &
PIDS+=($!)
echo "LightEtsy started (PID: $!, Port: 9067)"
sleep 1
fastmcp run software/LightEventbrite/app.py --transport http --host 0.0.0.0 --port 9068 &
PIDS+=($!)
echo "LightEventbrite started (PID: $!, Port: 9068)"
sleep 1
fastmcp run software/LightFedEx/app.py --transport http --host 0.0.0.0 --port 9069 &
PIDS+=($!)
echo "LightFedEx started (PID: $!, Port: 9069)"
sleep 1
fastmcp run software/LightFigma/app.py --transport http --host 0.0.0.0 --port 9070 &
PIDS+=($!)
echo "LightFigma started (PID: $!, Port: 9070)"
sleep 1
fastmcp run software/LightFreshdesk/app.py --transport http --host 0.0.0.0 --port 9071 &
PIDS+=($!)
echo "LightFreshdesk started (PID: $!, Port: 9071)"
sleep 1
fastmcp run software/LightGithub/app.py --transport http --host 0.0.0.0 --port 9072 &
PIDS+=($!)
echo "LightGithub started (PID: $!, Port: 9072)"
sleep 1
fastmcp run software/LightGitlab/app.py --transport http --host 0.0.0.0 --port 9073 &
PIDS+=($!)
echo "LightGitlab started (PID: $!, Port: 9073)"
sleep 1
fastmcp run software/LightGmail/app.py --transport http --host 0.0.0.0 --port 9074 &
PIDS+=($!)
echo "LightGmail started (PID: $!, Port: 9074)"
sleep 1
fastmcp run software/LightGoogleAnalytics/app.py --transport http --host 0.0.0.0 --port 9075 &
PIDS+=($!)
echo "LightGoogleAnalytics started (PID: $!, Port: 9075)"
sleep 1
fastmcp run software/LightGoogleCalendar/app.py --transport http --host 0.0.0.0 --port 9076 &
PIDS+=($!)
echo "LightGoogleCalendar started (PID: $!, Port: 9076)"
sleep 1
fastmcp run software/LightGoogleClassroom/app.py --transport http --host 0.0.0.0 --port 9077 &
PIDS+=($!)
echo "LightGoogleClassroom started (PID: $!, Port: 9077)"
sleep 1
fastmcp run software/LightGoogleDrive/app.py --transport http --host 0.0.0.0 --port 9078 &
PIDS+=($!)
echo "LightGoogleDrive started (PID: $!, Port: 9078)"
sleep 1
fastmcp run software/LightGoogleMaps/app.py --transport http --host 0.0.0.0 --port 9079 &
PIDS+=($!)
echo "LightGoogleMaps started (PID: $!, Port: 9079)"
sleep 1
fastmcp run software/LightGreenhouse/app.py --transport http --host 0.0.0.0 --port 9080 &
PIDS+=($!)
echo "LightGreenhouse started (PID: $!, Port: 9080)"
sleep 1
fastmcp run software/LightGusto/app.py --transport http --host 0.0.0.0 --port 9081 &
PIDS+=($!)
echo "LightGusto started (PID: $!, Port: 9081)"
sleep 1
fastmcp run software/LightHubspot/app.py --transport http --host 0.0.0.0 --port 9082 &
PIDS+=($!)
echo "LightHubspot started (PID: $!, Port: 9082)"
sleep 1
fastmcp run software/LightInstacart/app.py --transport http --host 0.0.0.0 --port 9083 &
PIDS+=($!)
echo "LightInstacart started (PID: $!, Port: 9083)"
sleep 1
fastmcp run software/LightInstagram/app.py --transport http --host 0.0.0.0 --port 9084 &
PIDS+=($!)
echo "LightInstagram started (PID: $!, Port: 9084)"
sleep 1
fastmcp run software/LightIntercom/app.py --transport http --host 0.0.0.0 --port 9085 &
PIDS+=($!)
echo "LightIntercom started (PID: $!, Port: 9085)"
sleep 1
fastmcp run software/LightJira/app.py --transport http --host 0.0.0.0 --port 9086 &
PIDS+=($!)
echo "LightJira started (PID: $!, Port: 9086)"
sleep 1
fastmcp run software/LightKlaviyo/app.py --transport http --host 0.0.0.0 --port 9087 &
PIDS+=($!)
echo "LightKlaviyo started (PID: $!, Port: 9087)"
sleep 1
fastmcp run software/LightKraken/app.py --transport http --host 0.0.0.0 --port 9088 &
PIDS+=($!)
echo "LightKraken started (PID: $!, Port: 9088)"
sleep 1
fastmcp run software/LightKubernetes/app.py --transport http --host 0.0.0.0 --port 9089 &
PIDS+=($!)
echo "LightKubernetes started (PID: $!, Port: 9089)"
sleep 1
fastmcp run software/LightLinear/app.py --transport http --host 0.0.0.0 --port 9090 &
PIDS+=($!)
echo "LightLinear started (PID: $!, Port: 9090)"
sleep 1
fastmcp run software/LightLinkedIn/app.py --transport http --host 0.0.0.0 --port 9091 &
PIDS+=($!)
echo "LightLinkedIn started (PID: $!, Port: 9091)"
sleep 1
fastmcp run software/LightMailchimp/app.py --transport http --host 0.0.0.0 --port 9092 &
PIDS+=($!)
echo "LightMailchimp started (PID: $!, Port: 9092)"
sleep 1
fastmcp run software/LightMailgun/app.py --transport http --host 0.0.0.0 --port 9093 &
PIDS+=($!)
echo "LightMailgun started (PID: $!, Port: 9093)"
sleep 1
fastmcp run software/LightMicrosoftTeams/app.py --transport http --host 0.0.0.0 --port 9094 &
PIDS+=($!)
echo "LightMicrosoftTeams started (PID: $!, Port: 9094)"
sleep 1
fastmcp run software/LightMixpanel/app.py --transport http --host 0.0.0.0 --port 9095 &
PIDS+=($!)
echo "LightMixpanel started (PID: $!, Port: 9095)"
sleep 1
fastmcp run software/LightMonday/app.py --transport http --host 0.0.0.0 --port 9096 &
PIDS+=($!)
echo "LightMonday started (PID: $!, Port: 9096)"
sleep 1
fastmcp run software/LightMyFitnessPal/app.py --transport http --host 0.0.0.0 --port 9097 &
PIDS+=($!)
echo "LightMyFitnessPal started (PID: $!, Port: 9097)"
sleep 1
fastmcp run software/LightNASA/app.py --transport http --host 0.0.0.0 --port 9098 &
PIDS+=($!)
echo "LightNASA started (PID: $!, Port: 9098)"
sleep 1
fastmcp run software/LightNotion/app.py --transport http --host 0.0.0.0 --port 9099 &
PIDS+=($!)
echo "LightNotion started (PID: $!, Port: 9099)"
sleep 1
fastmcp run software/LightObsidian/app.py --transport http --host 0.0.0.0 --port 9100 &
PIDS+=($!)
echo "LightObsidian started (PID: $!, Port: 9100)"
sleep 1
fastmcp run software/LightOkta/app.py --transport http --host 0.0.0.0 --port 9101 &
PIDS+=($!)
echo "LightOkta started (PID: $!, Port: 9101)"
sleep 1
fastmcp run software/LightOpenLibrary/app.py --transport http --host 0.0.0.0 --port 9102 &
PIDS+=($!)
echo "LightOpenLibrary started (PID: $!, Port: 9102)"
sleep 1
fastmcp run software/LightOpenWeather/app.py --transport http --host 0.0.0.0 --port 9103 &
PIDS+=($!)
echo "LightOpenWeather started (PID: $!, Port: 9103)"
sleep 1
fastmcp run software/LightOutlook/app.py --transport http --host 0.0.0.0 --port 9104 &
PIDS+=($!)
echo "LightOutlook started (PID: $!, Port: 9104)"
sleep 1
fastmcp run software/LightPagerDuty/app.py --transport http --host 0.0.0.0 --port 9105 &
PIDS+=($!)
echo "LightPagerDuty started (PID: $!, Port: 9105)"
sleep 1
fastmcp run software/LightPayPal/app.py --transport http --host 0.0.0.0 --port 9106 &
PIDS+=($!)
echo "LightPayPal started (PID: $!, Port: 9106)"
sleep 1
fastmcp run software/LightPinterest/app.py --transport http --host 0.0.0.0 --port 9107 &
PIDS+=($!)
echo "LightPinterest started (PID: $!, Port: 9107)"
sleep 1
fastmcp run software/LightPlaid/app.py --transport http --host 0.0.0.0 --port 9108 &
PIDS+=($!)
echo "LightPlaid started (PID: $!, Port: 9108)"
sleep 1
fastmcp run software/LightPostHog/app.py --transport http --host 0.0.0.0 --port 9109 &
PIDS+=($!)
echo "LightPostHog started (PID: $!, Port: 9109)"
sleep 1
fastmcp run software/LightQuickBooks/app.py --transport http --host 0.0.0.0 --port 9110 &
PIDS+=($!)
echo "LightQuickBooks started (PID: $!, Port: 9110)"
sleep 1
fastmcp run software/LightReddit/app.py --transport http --host 0.0.0.0 --port 9111 &
PIDS+=($!)
echo "LightReddit started (PID: $!, Port: 9111)"
sleep 1
fastmcp run software/LightRing/app.py --transport http --host 0.0.0.0 --port 9112 &
PIDS+=($!)
echo "LightRing started (PID: $!, Port: 9112)"
sleep 1
fastmcp run software/LightSalesforce/app.py --transport http --host 0.0.0.0 --port 9113 &
PIDS+=($!)
echo "LightSalesforce started (PID: $!, Port: 9113)"
sleep 1
fastmcp run software/LightSegment/app.py --transport http --host 0.0.0.0 --port 9114 &
PIDS+=($!)
echo "LightSegment started (PID: $!, Port: 9114)"
sleep 1
fastmcp run software/LightSendGrid/app.py --transport http --host 0.0.0.0 --port 9115 &
PIDS+=($!)
echo "LightSendGrid started (PID: $!, Port: 9115)"
sleep 1
fastmcp run software/LightSentry/app.py --transport http --host 0.0.0.0 --port 9116 &
PIDS+=($!)
echo "LightSentry started (PID: $!, Port: 9116)"
sleep 1
fastmcp run software/LightServiceNow/app.py --transport http --host 0.0.0.0 --port 9117 &
PIDS+=($!)
echo "LightServiceNow started (PID: $!, Port: 9117)"
sleep 1
fastmcp run software/LightShippo/app.py --transport http --host 0.0.0.0 --port 9118 &
PIDS+=($!)
echo "LightShippo started (PID: $!, Port: 9118)"
sleep 1
fastmcp run software/LightSlack/app.py --transport http --host 0.0.0.0 --port 9119 &
PIDS+=($!)
echo "LightSlack started (PID: $!, Port: 9119)"
sleep 1
fastmcp run software/LightSpotify/app.py --transport http --host 0.0.0.0 --port 9120 &
PIDS+=($!)
echo "LightSpotify started (PID: $!, Port: 9120)"
sleep 1
fastmcp run software/LightSquare/app.py --transport http --host 0.0.0.0 --port 9121 &
PIDS+=($!)
echo "LightSquare started (PID: $!, Port: 9121)"
sleep 1
fastmcp run software/LightStrava/app.py --transport http --host 0.0.0.0 --port 9122 &
PIDS+=($!)
echo "LightStrava started (PID: $!, Port: 9122)"
sleep 1
fastmcp run software/LightStripe/app.py --transport http --host 0.0.0.0 --port 9123 &
PIDS+=($!)
echo "LightStripe started (PID: $!, Port: 9123)"
sleep 1
fastmcp run software/LightTMDB/app.py --transport http --host 0.0.0.0 --port 9124 &
PIDS+=($!)
echo "LightTMDB started (PID: $!, Port: 9124)"
sleep 1
fastmcp run software/LightTelegram/app.py --transport http --host 0.0.0.0 --port 9125 &
PIDS+=($!)
echo "LightTelegram started (PID: $!, Port: 9125)"
sleep 1
fastmcp run software/LightTicketmaster/app.py --transport http --host 0.0.0.0 --port 9126 &
PIDS+=($!)
echo "LightTicketmaster started (PID: $!, Port: 9126)"
sleep 1
fastmcp run software/LightTrello/app.py --transport http --host 0.0.0.0 --port 9127 &
PIDS+=($!)
echo "LightTrello started (PID: $!, Port: 9127)"
sleep 1
fastmcp run software/LightTwilio/app.py --transport http --host 0.0.0.0 --port 9128 &
PIDS+=($!)
echo "LightTwilio started (PID: $!, Port: 9128)"
sleep 1
fastmcp run software/LightTwitch/app.py --transport http --host 0.0.0.0 --port 9129 &
PIDS+=($!)
echo "LightTwitch started (PID: $!, Port: 9129)"
sleep 1
fastmcp run software/LightTwitter/app.py --transport http --host 0.0.0.0 --port 9130 &
PIDS+=($!)
echo "LightTwitter started (PID: $!, Port: 9130)"
sleep 1
fastmcp run software/LightTypeform/app.py --transport http --host 0.0.0.0 --port 9131 &
PIDS+=($!)
echo "LightTypeform started (PID: $!, Port: 9131)"
sleep 1
fastmcp run software/LightUPS/app.py --transport http --host 0.0.0.0 --port 9132 &
PIDS+=($!)
echo "LightUPS started (PID: $!, Port: 9132)"
sleep 1
fastmcp run software/LightUber/app.py --transport http --host 0.0.0.0 --port 9133 &
PIDS+=($!)
echo "LightUber started (PID: $!, Port: 9133)"
sleep 1
fastmcp run software/LightVimeo/app.py --transport http --host 0.0.0.0 --port 9134 &
PIDS+=($!)
echo "LightVimeo started (PID: $!, Port: 9134)"
sleep 1
fastmcp run software/LightWebflow/app.py --transport http --host 0.0.0.0 --port 9135 &
PIDS+=($!)
echo "LightWebflow started (PID: $!, Port: 9135)"
sleep 1
fastmcp run software/LightWhatsApp/app.py --transport http --host 0.0.0.0 --port 9136 &
PIDS+=($!)
echo "LightWhatsApp started (PID: $!, Port: 9136)"
sleep 1
fastmcp run software/LightWooCommerce/app.py --transport http --host 0.0.0.0 --port 9137 &
PIDS+=($!)
echo "LightWooCommerce started (PID: $!, Port: 9137)"
sleep 1
fastmcp run software/LightWordPress/app.py --transport http --host 0.0.0.0 --port 9138 &
PIDS+=($!)
echo "LightWordPress started (PID: $!, Port: 9138)"
sleep 1
fastmcp run software/LightXero/app.py --transport http --host 0.0.0.0 --port 9139 &
PIDS+=($!)
echo "LightXero started (PID: $!, Port: 9139)"
sleep 1
fastmcp run software/LightYelp/app.py --transport http --host 0.0.0.0 --port 9140 &
PIDS+=($!)
echo "LightYelp started (PID: $!, Port: 9140)"
sleep 1
fastmcp run software/LightYouTube/app.py --transport http --host 0.0.0.0 --port 9141 &
PIDS+=($!)
echo "LightYouTube started (PID: $!, Port: 9141)"
sleep 1
fastmcp run software/LightZendesk/app.py --transport http --host 0.0.0.0 --port 9142 &
PIDS+=($!)
echo "LightZendesk started (PID: $!, Port: 9142)"
sleep 1
fastmcp run software/LightZillow/app.py --transport http --host 0.0.0.0 --port 9143 &
PIDS+=($!)
echo "LightZillow started (PID: $!, Port: 9143)"
sleep 1
fastmcp run software/LightZoom/app.py --transport http --host 0.0.0.0 --port 9144 &
PIDS+=($!)
echo "LightZoom started (PID: $!, Port: 9144)"
sleep 1
echo "All applications started successfully. Press Ctrl+C to shut down all applications."

# Wait for all processes
for PID in "${PIDS[@]}"; do
    wait $PID
done
