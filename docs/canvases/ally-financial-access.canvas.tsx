import {
  BarChart,
  Callout,
  Card,
  CardBody,
  CardHeader,
  Grid,
  H1,
  H2,
  Stack,
  Stat,
  Table,
  Text,
} from "cursor/canvas";

const SESSIONS = [
  { when: "9 Sep 12:00–12:52 PM ET", reqs: 253, ua: "Mac Chrome 152", note: "Opened / and loaded the Streamlit UI" },
  { when: "9 Sep 1:32–1:50 PM ET", reqs: 3, ua: "Windows Edge 151", note: "health / host-config / stream" },
  { when: "9 Sep 2:37–2:58 PM ET", reqs: 41, ua: "Windows Edge 151", note: "Widget JS + stream reconnect" },
  { when: "9 Sep 3:41–3:46 PM ET", reqs: 8, ua: "Windows Edge 151", note: "stream + health" },
  { when: "10 Sep 9:48 AM ET", reqs: 2, ua: "Mac Chrome 152", note: "health + host-config only" },
  { when: "10 Sep 2:41–3:15 PM ET", reqs: 18, ua: "Mac Chrome 152", note: "6 stream reconnects" },
  { when: "10 Sep 5:35–5:36 PM ET", reqs: 4, ua: "Mac Chrome 152", note: "short reconnect" },
  { when: "11 Sep 11:21–11:56 AM ET", reqs: 22, ua: "Windows Edge 152", note: "ImageList / widget JS; downloaded /sources.zip" },
  { when: "11 Sep 12:33–12:53 PM ET", reqs: 64, ua: "Windows Edge 152", note: "Autocomplete / TextInput / JSON view" },
  { when: "11 Sep 1:25–1:59 PM ET", reqs: 7, ua: "Windows Edge 152", note: "stream reconnects" },
  { when: "16 Sep 9:25–9:53 AM ET", reqs: 157, ua: "Windows Edge 152", note: "Returned; opened / and reloaded full UI" },
  { when: "16 Sep 10:46 AM ET", reqs: 1, ua: "Windows Edge 152", note: "stream reconnect" },
  { when: "16 Sep 1:06–1:10 PM ET", reqs: 16, ua: "Windows Edge 152", note: "health/host-config; 10× 502 backend blip" },
  { when: "16 Sep 1:46 PM ET", reqs: 3, ua: "Windows Edge 152", note: "short reconnect" },
  { when: "16 Sep 2:27 PM ET", reqs: 3, ua: "Windows Edge 152", note: "short reconnect" },
  { when: "16 Sep 3:43 PM ET", reqs: 1, ua: "Windows Edge 152", note: "last Ally hit (stream)" },
];

export default function AllyFinancialAccess() {
  return (
    <Stack gap={20}>
      <H1>Ally Financial access to 54.147.137.184</H1>
      <Text tone="secondary">
        Source: nginx access.log · Ally ARIN ranges 198.74.80.0/20 (ALLY-FINANCIAL) and 74.114.112.0/22 (ALLY-INVEST) · 7–17 Sep 2026 (refreshed 17 Sep)
      </Text>

      <Callout tone="info" title="One corporate egress IP — returned on 16 Sep">
        Every Ally hit came from 198.74.88.193 (NAT). No traffic from ALLY-INVEST 74.114.112.0/22. User-agents show Mac Chrome 152 and Windows Edge 151/152. After a quiet stretch (12–15 Sep), Windows Edge 152 came back on 16 Sep with 181 requests and a fresh open of /.
      </Callout>

      <Grid columns={4} gap={12}>
        <Stat value="603" label="Requests" />
        <Stat value="1" label="Source IP" />
        <Stat value="16" label="Sessions (30-min gap)" />
        <Stat value="4" label="Days: 9–11 + 16 Sep" />
      </Grid>

      <H2>Requests by day</H2>
      <Text tone="secondary" size="small">
        Nginx request count from 198.74.88.193. Most volume is Streamlit static JS after the first page load.
      </Text>
      <BarChart
        height={200}
        categories={["9 Sep", "10 Sep", "11 Sep", "16 Sep"]}
        series={[{ name: "Requests", data: [305, 24, 93, 181], tone: "info" }]}
      />

      <H2>Requests by hour (UTC)</H2>
      <Text tone="secondary" size="small">
        Hour starting time in UTC. Convert to ET by subtracting 4 hours (EDT).
      </Text>
      <BarChart
        height={240}
        categories={[
          "9 Sep 16h",
          "17h",
          "18h",
          "19h",
          "10 Sep 13h",
          "18h",
          "19h",
          "21h",
          "11 Sep 15h",
          "16h",
          "17h",
          "16 Sep 13h",
          "14h",
          "17h",
          "18h",
          "19h",
        ]}
        series={[
          {
            name: "Requests",
            data: [253, 3, 41, 8, 2, 13, 5, 4, 22, 64, 7, 157, 1, 19, 3, 1],
            tone: "success",
          },
        ]}
      />

      <Card>
        <CardHeader>Sessions</CardHeader>
        <CardBody>
          <Table
            headers={["When (ET)", "Reqs", "Client", "What happened"]}
            columnAlign={["left", "right", "left", "left"]}
            rows={SESSIONS.map((s) => [s.when, String(s.reqs), s.ua, s.note])}
          />
        </CardBody>
      </Card>

      <Card>
        <CardHeader>Browsers</CardHeader>
        <CardBody>
          <Table
            headers={["User-agent", "Requests"]}
            columnAlign={["left", "right"]}
            rows={[
              ["Windows Edge 152", "274"],
              ["Windows Edge 151", "167"],
              ["Mac Chrome 152", "162"],
            ]}
          />
        </CardBody>
      </Card>

      <Card>
        <CardHeader>App paths vs Streamlit chrome</CardHeader>
        <CardBody>
          <Table
            headers={["Path", "Hits", "Meaning"]}
            columnAlign={["left", "right", "left"]}
            rows={[
              ["/_stcore/host-config", "34", "UI bootstrap"],
              ["/_stcore/health", "34", "UI heartbeat"],
              ["/_stcore/stream", "29", "Live Streamlit websocket (mostly 101)"],
              ["/", "3", "Opened homepage (9 Sep ×2, 16 Sep ×1)"],
              ["/sources.zip", "1", "Downloaded source zip (11 Sep)"],
              ["All other /static and /lib", "~499", "Streamlit JS/CSS/fonts after load"],
            ]}
          />
        </CardBody>
      </Card>

      <Callout tone="neutral" title="What they did not do">
        No /docs, /health, /api/agent/run, or exploit paths from Ally space. All Ally requests were GET (564 × 200, 29 × 101, 10 × 502 on 16 Sep 1:10 PM ET health/host-config during a brief backend blip). First hit 9 Sep 12:00 PM ET; last hit 16 Sep 3:43 PM ET. No Ally traffic 12–15 Sep or on 17 Sep through scan time.
      </Callout>
    </Stack>
  );
}
