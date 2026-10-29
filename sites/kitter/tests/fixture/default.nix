# The fake X (server.py) for the VM tests: `module` runs it on a NixOS machine whose /etc/hosts sends X's names to
# it, and `tls` holds the test CA (ca.pem), whose certificate it serves for all four names. Made at build time; the
# key is a test key.
{pkgs}: let
  names = ["x.com" "abs.twimg.com" "pbs.twimg.com" "video.twimg.com"];
  # twscrape's recordings (MIT): a list timeline, the source of the home and list pages (pages.py), and
  # @XDevelopers' profile and posts, one of its posts with its replies, and a community's posts.
  twscrape = name: hash:
    pkgs.fetchurl {
      url = "https://raw.githubusercontent.com/vladkens/twscrape/63f61a518e576ea5c132f1156c03dda0520d76c1/tests/mocked-data/${name}.json";
      inherit hash;
    };
  recorded = twscrape "raw_list_timeline" "sha256-NDH8bJ1OM1OblJUU9OBwS+QBhEecAr9mbg7CENPYm8E=";
  user = twscrape "raw_user_by_login" "sha256-3GA1n8za5LyBNOuUYFTUApEKrWHKC+DGjOOsIw1td/I=";
  userTweets = twscrape "raw_user_tweets" "sha256-biXMMoizEOqvi3uNYKoFVePPx/sx6R0+kcZRMffNTOc=";
  community = twscrape "raw_community_tweets" "sha256-rknQhqqpvCHiGiF0RqWuNhJB/GvAbN8+lI6/mG0JV1I=";
  detail = twscrape "raw_tweet_details" "sha256-PDpmlOaf/aFPv/g1hKYeOJxhleVXymkvdxS2ZRofXjw=";
  # Another account's posts and replies, answered as @XDevelopers' Replies tab; its Media tab is its own.
  replies = twscrape "raw_user_tweets_and_replies" "sha256-HEddcoRbhdwnjXaG9wRKCxAT0jwfFE8Vn7Q0HWfgXvI=";
  media = twscrape "raw_user_media" "sha256-Y3a/udrGOhjA4Z6Qdep41hQ/XnkkWSAicMmIWO6lS84=";
  tls = pkgs.runCommand "kitter-test-ca" {nativeBuildInputs = [pkgs.openssl];} ''
    mkdir $out && cd $out
    openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:P-256 -nodes -days 3650 -subj "/CN=kitter test CA" \
      -addext basicConstraints=critical,CA:TRUE -addext keyUsage=critical,keyCertSign,cRLSign \
      -keyout ca.key -out ca.pem
    openssl req -newkey ec -pkeyopt ec_paramgen_curve:P-256 -nodes -subj "/CN=x.com" -keyout server.key -out server.csr
    printf '%s\n' subjectAltName=${pkgs.lib.concatMapStringsSep "," (n: "DNS:${n}") names} basicConstraints=CA:FALSE \
      keyUsage=critical,digitalSignature extendedKeyUsage=serverAuth >ext.cnf
    openssl x509 -req -in server.csr -CA ca.pem -CAkey ca.key -CAcreateserial -days 3650 -extfile ext.cnf -out server.pem
    rm ca.key server.csr ext.cnf ca.srl
  '';
  data = pkgs.runCommand "kitter-fake-x-data" {nativeBuildInputs = [pkgs.python3 pkgs.ffmpeg-headless pkgs.jq];} ''
    mkdir $out
    python3 -I ${./pages.py} ${recorded} $out
    cp ${userTweets} $out/user-tweets.json && cp ${community} $out/community.json
    cp ${replies} $out/user-replies.json && cp ${media} $out/user-media.json
    # A bio that names an account, for which X marks no entity (as on Oct 28, 2026), and an address that names none.
    jq '.data.user.result.profile_bio.description += " Ask @API, not dev@x.com."' ${user} > $out/user.json
    # McFaul's post with no replies, as X answers one (Oct 28, 2026): the post, "Discover more", then a bottom cursor
    # that pages only more of it.
    jq -n --slurpfile feed ${recorded} '
      def entry($id): $feed[0] | [.. | objects | select(.itemContent?.tweet_results?.result?.rest_id? == $id)][0];
      {data: {threaded_conversation_with_injections_v2: {instructions: [{type: "TimelineAddEntries", entries: [
        {entryId: "tweet-2112986636392833489", content: entry("2112986636392833489")},
        {entryId: "tweetdetailrelatedtweets-2", content: {entryType: "TimelineTimelineModule",
          items: [{item: entry("2112996103201448049")}]}},
        {entryId: "cursor-bottom-2", content: {entryType: "TimelineTimelineCursor", cursorType: "Bottom", value: "kitter-test-lonely"}}
      ]}]}}}
    ' > $out/lonely.json
    # The post's page with the "Discover more" module X has since added (as on Oct 28, 2026), holding McFaul's post
    # from the feed: posts from across X that kitter leaves out.
    jq --slurpfile feed ${recorded} '
      ($feed[0] | [.. | objects | select(.itemContent?.tweet_results?.result?.rest_id? == "2112986636392833489")][0]) as $plain
      | (.. | objects | select(.type? == "TimelineAddEntries") | .entries) += [{entryId: "tweetdetailrelatedtweets-1",
        content: {entryType: "TimelineTimelineModule", header: {text: "Discover more"},
          clientEventInfo: {component: "related_tweet"}, items: [{item: $plain}]}}]
    ' ${detail} > $out/post.json
    # A photo at X's two sizes (`small` is 680 px wide at most, `large` 2048), an avatar, and a 2 s H.264 clip
    # for every video and GIF.
    still() { ffmpeg -loglevel error -f lavfi -i "color=c=0x8caaee:s=$1" -frames:v 1 "$out/$2.jpg"; }
    still 680x383 small && still 2048x1152 large && still 48x48 avatar
    ffmpeg -loglevel error -f lavfi -i testsrc=size=320x180:rate=10 -t 2 -c:v libx264 -pix_fmt yuv420p \
      -movflags +faststart $out/video.mp4
  '';
in {
  inherit tls recorded;
  module = {
    networking.hosts."127.0.0.1" = names;
    systemd.services.fake-x = {
      wantedBy = ["multi-user.target"];
      serviceConfig.ExecStart = "${pkgs.python3}/bin/python3 -I ${./server.py} ${data} ${tls} ${../../api/src/graphql.json} /var/log/fake-x.log";
    };
  };
}
