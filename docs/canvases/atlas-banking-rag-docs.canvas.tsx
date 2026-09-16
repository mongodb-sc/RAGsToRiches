import {
  Callout,
  Card,
  CardBody,
  CardHeader,
  Divider,
  Grid,
  H1,
  H2,
  H3,
  Link,
  Pill,
  Row,
  Stack,
  Stat,
  Table,
  Text,
  useHostTheme,
} from "cursor/canvas";

const BUILD_PROMPT = `Create a complete Python FastAPI + Streamlit application that demonstrates MongoDB Atlas as a RAG and Data Platform for retail banking.

Project structure: app/main.py, app/config.py, app/services/database.py, vector_search.py, graph_service.py, security.py, app/scripts/seed_data.py, ui/app.py, requirements.txt.

Requirements:
1. Seed 50 customers, 100 accounts, 20 policy documents. Embed with OpenAI text-embedding-3-small into knowledge_base. Link households and joint accounts for multi-tier graph traversals.
2. $vectorSearch with pre-filters on product_type and clearance_level. Dynamic prompt synthesis plus chat generation.
3. $graphLookup for a customer's financial graph. PyVis-ready JSON.
4. filter_context_by_role: tier1_support redacts PII and public KB only; compliance_manager sees transcripts and private metadata.
5. Streamlit tabs: Banking RAG Assistant, Knowledge Graph, Governance & Security.

Use your Atlas MONGODB_URI from .env and official MongoDB logos and branding.`;

export default function AtlasBankingRagDocs() {
  const theme = useHostTheme();

  return (
    <Stack gap={28} style={{ padding: 24, maxWidth: 980 }}>
      <Stack gap={8}>
        <Row gap={8} align="center">
          <Pill active>Atlas</Pill>
          <Pill>RAG</Pill>
          <Pill>$graphLookup</Pill>
          <Pill>Cursor prompts</Pill>
        </Row>
        <H1>Retail banking RAG on MongoDB Atlas</H1>
        <Text tone="secondary">
          Source-linked documentation for the FastAPI + Streamlit demo: Cursor
          prompts that built it, product requirements, three browser use cases,
          and the MongoDB docs each pipeline implements.
        </Text>
      </Stack>

      <Row gap={24}>
        <Stat value="4" label="Cursor prompts in this session" />
        <Stat value="3" label="Browser use cases" />
        <Stat value="50 / 100" label="Customers / accounts seeded" />
      </Row>

      <Callout tone="info" title="Open beside the chat">
        This canvas is the durable walkthrough. Source files also cite the
        official MongoDB pages next to the aggregation they run.
      </Callout>

      <Divider />

      <Stack gap={12}>
        <H2>Cursor prompts</H2>
        <Text>
          These are the exact Cursor agent prompts from this project session.
          Paste them into a new chat to rebuild or extend the demo.
        </Text>

        <Table
          headers={["#", "When", "Prompt", "What it produced"]}
          columnAlign={["left", "left", "left", "left"]}
          rows={[
            [
              "1",
              "4:21 PM",
              "Build FastAPI + Streamlit Atlas RAG/data platform",
              "app/, ui/, seed, Vector Search, $graphLookup, governance",
            ],
            [
              "2",
              "4:41 PM",
              "add screenpipe mcp server so you can do screen recordings",
              "~/.cursor/mcp.json screenpipe entry + local recorder on :3030",
            ],
            [
              "3",
              "4:44 PM",
              "Document source with MongoDB links, use cases, walkthroughs; record in the browser",
              "Module docstrings + this canvas + Screenpipe capture plan",
            ],
            [
              "4",
              "4:46 PM",
              "add the cursor prompts to the documentation.",
              "This section, plus prompt notes in app/main.py and ui/app.py",
            ],
          ]}
          striped
        />

        <Card collapsible defaultOpen>
          <CardHeader trailing={<Pill size="sm">Prompt 1 · build</Pill>}>
            Original product brief
          </CardHeader>
          <CardBody>
            <Text size="small" tone="secondary">
              {BUILD_PROMPT}
            </Text>
          </CardBody>
        </Card>

        <Grid columns={1} gap={12}>
          <Card collapsible defaultOpen={false}>
            <CardHeader trailing={<Pill size="sm">Prompt 2 · MCP</Pill>}>
              Screenpipe
            </CardHeader>
            <CardBody>
              <Text>
                add screenpipe mcp server so you can do screen recordings
              </Text>
              <Text size="small" tone="secondary">
                Registers npx -y screenpipe-mcp against http://localhost:3030.
                Reload Cursor after adding MCP servers.
              </Text>
            </CardBody>
          </Card>
          <Card collapsible defaultOpen={false}>
            <CardHeader trailing={<Pill size="sm">Prompt 3 · docs</Pill>}>
              Documentation and recordings
            </CardHeader>
            <CardBody>
              <Text>
                document source code with mongodb doc links, use cases,
                requirements, and walk through of each use case. Use screenpipe
                to record performing each use case in the broswer app.
              </Text>
            </CardBody>
          </Card>
          <Card collapsible defaultOpen={false}>
            <CardHeader trailing={<Pill size="sm">Prompt 4 · this ask</Pill>}>
              Include the prompts
            </CardHeader>
            <CardBody>
              <Text>add the cursor prompts to the documentation.</Text>
              <Text size="small" tone="secondary">
                Listed here and referenced from app/main.py and ui/app.py.
              </Text>
            </CardBody>
          </Card>
        </Grid>
      </Stack>

      <Divider />

      <Stack gap={12}>
        <H2>Requirements mapped to source</H2>
        <Table
          headers={["Requirement", "Source", "MongoDB capability"]}
          rows={[
            [
              "50 customers, 100 accounts, 20 policies, household/joint links",
              "app/scripts/seed_data.py",
              "Collections + Vector Search / Search indexes",
            ],
            [
              "$vectorSearch + metadata pre-filter + prompt synthesis",
              "app/services/vector_search.py",
              "$vectorSearch, $rankFusion, $search",
            ],
            [
              "Customer financial graph as PyVis JSON",
              "app/services/graph_service.py",
              "$graphLookup + $lookup",
            ],
            [
              "filter_context_by_role Tier 1 vs Compliance",
              "app/services/security.py",
              "Vector Search pre-filter on clearance_level",
            ],
            [
              "Three-tab branded Streamlit dashboard",
              "ui/app.py",
              "Same services as the FastAPI surface",
            ],
          ]}
          striped
        />
      </Stack>

      <Divider />

      <Stack gap={16}>
        <H2>Use cases and walkthroughs</H2>
        <Text tone="secondary">
          Run Streamlit at http://localhost:8501. Sidebar persona applies to
          RAG retrieval and graph metadata redaction.
        </Text>

        <Card>
          <CardHeader trailing={<Pill size="sm" active>Tab 1</Pill>}>
            Banking RAG Assistant
          </CardHeader>
          <CardBody>
            <Stack gap={8}>
              <H3>Requirement</H3>
              <Text>
                A contact-center agent asks a policy question. Atlas retrieves
                grounded passages with vector scores; the LLM cites them.
              </Text>
              <H3>Walkthrough</H3>
              <Text>
                1. Keep persona on Tier 1 Agent. 2. Leave product filter on
                all, search mode hybrid. 3. Click “What is the outgoing
                domestic wire fee?” 4. Confirm the answer is $25 and citation
                [1] is Personal Checking Fee Schedule. 5. Switch persona to
                Compliance Manager and ask “What CIP data is required?” —
                restricted POL-016 and transcripts appear.
              </Text>
              <H3>Demo prompts</H3>
              <Text>
                What is the outgoing domestic wire fee?
              </Text>
              <Text>
                When are check deposits available under Regulation CC?
              </Text>
              <Text>
                Can either joint owner close a checking account?
              </Text>
              <Text>What CIP data is required to open an account?</Text>
              <Text size="small" tone="secondary">
                Implementation: rag_chat in app/services/vector_search.py,
                POST /api/chat in app/main.py, first tab in ui/app.py.
              </Text>
            </Stack>
          </CardBody>
        </Card>

        <Card>
          <CardHeader trailing={<Pill size="sm" active>Tab 2</Pill>}>
            Knowledge Graph
          </CardHeader>
          <CardBody>
            <Stack gap={8}>
              <H3>Requirement</H3>
              <Text>
                A banker expands one customer into household members, joint
                accounts, and recent joint transactions without application-side
                recursion.
              </Text>
              <H3>Walkthrough</H3>
              <Text>
                1. Open Knowledge Graph. 2. Select CUST-0001. 3. Set traversal
                depth to 3. 4. Click Run $graphLookup. 5. Confirm the PyVis
                canvas plus node/edge counts. 6. Expand Structured JSON and
                Aggregation pipeline. 7. Toggle Tier 1 in the sidebar — SSN
                and exact balances redact on node hover text.
              </Text>
              <Text size="small" tone="secondary">
                Implementation: build_graph_lookup_pipeline and
                get_customer_graph in app/services/graph_service.py, GET
                /api/graph/{"{customer_id}"}.
              </Text>
            </Stack>
          </CardBody>
        </Card>

        <Card>
          <CardHeader trailing={<Pill size="sm" active>Tab 3</Pill>}>
            Governance and Security
          </CardHeader>
          <CardBody>
            <Stack gap={8}>
              <H3>Requirement</H3>
              <Text>
                The same retrieved set must shrink and redact when the caller
                is a Tier 1 agent, and stay complete for a compliance manager.
              </Text>
              <H3>Walkthrough</H3>
              <Text>
                1. Open Governance & Security. 2. With Tier 1 Agent selected,
                only the public fee-schedule chunk remains; SSN, account
                numbers, and customer balances are gone. 3. Switch to
                Compliance Manager. 4. Restricted CIP policy, service
                transcript, and private account metadata reappear with raw
                SSN and balance values.
              </Text>
              <Text size="small" tone="secondary">
                Implementation: filter_context_by_role in
                app/services/security.py, POST /api/governance/filter.
              </Text>
            </Stack>
          </CardBody>
        </Card>
      </Stack>

      <Divider />

      <Stack gap={12}>
        <H2>MongoDB documentation</H2>
        <Text>
          Official pages cited in the service module docstrings. Open them
          beside the matching pipeline.
        </Text>
        <Table
          headers={["Topic", "Used in", "Docs"]}
          rows={[
            [
              "$vectorSearch + pre-filter",
              "vector_search.py",
              <Link href="https://www.mongodb.com/docs/atlas/atlas-vector-search/vector-search-stage/">
                Vector Search stage
              </Link>,
            ],
            [
              "$rankFusion hybrid",
              "vector_search.py",
              <Link href="https://www.mongodb.com/docs/manual/reference/operator/aggregation/rankFusion/">
                $rankFusion
              </Link>,
            ],
            [
              "RRF tutorial",
              "vector_search.py",
              <Link href="https://www.mongodb.com/docs/atlas/atlas-vector-search/tutorials/reciprocal-rank-fusion/">
                Reciprocal Rank Fusion
              </Link>,
            ],
            [
              "Atlas Search $search",
              "vector_search.py",
              <Link href="https://www.mongodb.com/docs/atlas/atlas-search/aggregation-stages/search/">
                $search
              </Link>,
            ],
            [
              "LangChain + Atlas",
              "vector_search.py",
              <Link href="https://www.mongodb.com/docs/atlas/atlas-vector-search/ai-integrations/langchain/">
                LangChain integration
              </Link>,
            ],
            [
              "$graphLookup",
              "graph_service.py",
              <Link href="https://www.mongodb.com/docs/manual/reference/operator/aggregation/graphLookup/">
                $graphLookup
              </Link>,
            ],
            [
              "Aggregation pipeline",
              "graph_service.py",
              <Link href="https://www.mongodb.com/docs/manual/core/aggregation-pipeline/">
                Aggregation
              </Link>,
            ],
            [
              "PyMongo pools",
              "database.py",
              <Link href="https://www.mongodb.com/docs/languages/python/pymongo-driver/current/connect/connection-options/">
                Connection options
              </Link>,
            ],
            [
              "Vector index type",
              "seed_data.py",
              <Link href="https://www.mongodb.com/docs/atlas/atlas-vector-search/vector-search-type/">
                Vector Search index
              </Link>,
            ],
            [
              "Queryable Encryption",
              "security.py",
              <Link href="https://www.mongodb.com/docs/manual/core/queryable-encryption/">
                Production PII path
              </Link>,
            ],
          ]}
        />
      </Stack>

      <Divider />

      <Stack gap={8}>
        <H2>How to run</H2>
        <Text>
          source .venv/bin/activate then python -m app.scripts.seed_data
        </Text>
        <Text>uvicorn app.main:app --reload --port 8000</Text>
        <Text>streamlit run ui/app.py</Text>
        <Text tone="secondary" size="small">
          UI: http://localhost:8501 · API docs: http://127.0.0.1:8000/docs ·
          Host theme: {theme.kind}.
        </Text>
      </Stack>
    </Stack>
  );
}
