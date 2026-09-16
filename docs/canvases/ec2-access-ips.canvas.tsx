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

const TOP_IPS = [
  { ip: "147.90.209.15", requests: 25778, days: 1, kind: "Scanner", note: "8-minute burst today; 24,490 unique exploit paths" },
  { ip: "104.30.164.7", requests: 1468, days: 11, kind: "Browser", note: "Streamlit UI + websockets; Atlas Auto Setup IP" },
  { ip: "3.149.181.223", requests: 930, days: 11, kind: "Scanner", note: "AWS; /mcp, /docs, swagger probes" },
  { ip: "3.143.160.35", requests: 857, days: 11, kind: "Scanner", note: "AWS; daily probes" },
  { ip: "3.22.21.6", requests: 460, days: 10, kind: "Scanner", note: "AWS; daily probes" },
  { ip: "198.74.88.193", requests: 422, days: 1, kind: "Mixed", note: "High volume, short window" },
  { ip: "8.228.2.75", requests: 349, days: 1, kind: "Scanner", note: "Mostly non-app paths" },
  { ip: "136.83.60.123", requests: 301, days: 1, kind: "Scanner", note: "Sep 7–8; .env / php-cgi / /etc/passwd" },
];

const HOMEPAGE = [
  { ip: "3.149.181.223", hits: 50 },
  { ip: "3.143.160.35", hits: 42 },
  { ip: "185.218.86.25", hits: 33 },
  { ip: "104.30.164.7", hits: 33 },
  { ip: "3.22.21.6", hits: 15 },
  { ip: "136.83.60.123", hits: 14 },
];

export default function Ec2AccessIps() {
  return (
    <Stack gap={20}>
      <H1>EC2 access by IP — 54.147.137.184</H1>
      <Text tone="secondary">
        Source: nginx access.log on ip-172-31-2-245 · 5 Sep 2026 00:02 UTC through 15 Sep 2026 19:02 UTC · 35,209 requests · 669 unique IPs
      </Text>

      <Callout tone="warning" title="This is not the NIQ portal">
        This instance serves Atlas National Bank at https://54.147.137.184.sslip.io (FastAPI + Streamlit). NIQ Search Demo was never deployed here. No request path or user-agent contained niq, nielsen, or delivery.
      </Callout>

      <Grid columns={4} gap={12}>
        <Stat value="35,209" label="Nginx requests" />
        <Stat value="669" label="Unique client IPs" />
        <Stat value="147.90.209.15" label="Most requests" tone="danger" />
        <Stat value="104.30.164.7" label="Most persistent browser" tone="info" />
      </Grid>

      <H2>Request volume by client IP</H2>
      <Text tone="secondary" size="small">
        Request count (nginx lines) for the eight busiest source IPs. 147.90.209.15 is a same-day exploit scan, not a product user.
      </Text>
      <BarChart
        horizontal
        height={280}
        categories={TOP_IPS.map((row) => row.ip)}
        series={[{ name: "Requests", data: TOP_IPS.map((row) => row.requests), tone: "info" }]}
      />

      <H2>GET / homepage hits</H2>
      <Text tone="secondary" size="small">
        Status 200/301/302 on path / only. Better signal for “who opened the site” than raw request volume.
      </Text>
      <BarChart
        horizontal
        height={220}
        categories={HOMEPAGE.map((row) => row.ip)}
        series={[{ name: "Homepage hits", data: HOMEPAGE.map((row) => row.hits), tone: "success" }]}
      />

      <Card>
        <CardHeader>Top IPs by total use</CardHeader>
        <CardBody>
          <Table
            headers={["IP", "Requests", "Days seen", "Kind", "What they did"]}
            rows={TOP_IPS.map((row) => [row.ip, row.requests.toLocaleString(), String(row.days), row.kind, row.note])}
            rowTone={TOP_IPS.map((row) =>
              row.kind === "Browser" ? "info" : row.kind === "Scanner" ? "danger" : undefined,
            )}
          />
        </CardBody>
      </Card>

      <Callout tone="info" title="Who actually used the app">
        Yes — the site was hit. Almost all volume is automated scanning. The only IP that looks like a real session is 104.30.164.7: Mac Chrome, Streamlit /_stcore/stream websockets, 33 homepage loads, present all 11 log days. That address is also on the Atlas allowlist as Auto Setup.
      </Callout>
    </Stack>
  );
}
