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
  { when: "9 Sep 1:32–1:50 PM ET", reqs: 3, ua: "Streamlit keepalive", note: "health / host-config / stream" },
  { when: "9 Sep 2:37–2:58 PM ET", reqs: 41, ua: "UI assets", note: "Widget JS + stream reconnect" },
  { when: "9 Sep 3:41–3:46 PM ET", reqs: 8, ua: "Streamlit keepalive", note: "stream + health" },
  { when: "10 Sep 9:48 AM ET", reqs: 2, ua: "Streamlit keepalive", note: "health + host-config only" },
  { when: "10 Sep 2:41–3:15 PM ET", reqs: 18, ua: "Streamlit keepalive", note: "6 stream reconnects" },
  { when: "10 Sep 5:35–5:36 PM ET", reqs: 4, ua: "Streamlit keepalive", note: "short reconnect" },
  { when: "11 Sep 11:21–11:56 AM ET", reqs: 22, ua: "UI assets", note: "ImageList / widget JS" },
  { when: "11 Sep 12:33–12:53 PM ET", reqs: 64, ua: "Windows Edge 152", note: "Autocomplete / TextInput / JSON view" },
  { when: "11 Sep 1:25–1:59 PM ET", reqs: 7, ua: "Windows Edge 152", note: "stream reconnects; last hit 1:59 PM ET" },
];

export default function AllyFinancialAccess() {
  return (
    <Stack gap={20}>
      <H1>Ally Financial access to 54.147.137.184</H1>
      <Text tone="secondary">
        Source: nginx access.log · Ally ARIN ranges 198.74.80.0/20 (ALLY-FINANCIAL) and 74.114.112.0/22 (ALLY-INVEST) · 5–15 Sep 2026
      </Text>

      <Callout tone="info" title="One corporate egress IP, two browsers">
        Every Ally hit came from 198.74.88.193 (NAT). No traffic from ALLY-INVEST 74.114.112.0/22. User-agents show Mac Chrome 152 and Windows Edge 151/152 — at least two people or two machines behind the same Ally firewall.
      </Callout>

      <Grid columns={4} gap={12}>
        <Stat value="422" label="Requests" />
        <Stat value="1" label="Source IP" />
        <Stat value="10" label="Sessions (30-min gap)" />
        <Stat value="3" label="Days: 9–11 Sep" />
      </Grid>

      <H2>Requests by day</H2>
      <Text tone="secondary" size="small">
        Nginx request count from 198.74.88.193. Most volume is Streamlit static JS after the first page load.
      </Text>
      <BarChart
        height={200}
        categories={["9 Sep", "10 Sep", "11 Sep"]}
        series={[{ name: "Requests", data: [305, 24, 93], tone: "info" }]}
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
        ]}
        series={[{ name: "Requests", data: [253, 3, 41, 8, 2, 13, 5, 4, 22, 64, 7], tone: "success" }]}
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
              ["Windows Edge 151", "167"],
              ["Mac Chrome 152", "162"],
              ["Windows Edge 152", "93"],
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
              ["/_stcore/stream", "22", "Live Streamlit websocket (status 101)"],
              ["/_stcore/health", "22", "UI heartbeat"],
              ["/_stcore/host-config", "22", "UI bootstrap"],
              ["/", "2", "Opened the banking demo homepage"],
              ["/sources.zip", "1", "Downloaded the source zip"],
              ["All other /static and /lib", "353", "Streamlit JS/CSS/fonts after load"],
            ]}
          />
        </CardBody>
      </Card>

      <Callout tone="neutral" title="What they did not do">
        No /docs, /health, /api/agent/run, or exploit paths from Ally space. Every request was GET and succeeded (400 × 200, 22 × 101). First hit 9 Sep 12:00 PM ET; last hit 11 Sep 1:59 PM ET.
      </Callout>
    </Stack>
  );
}
