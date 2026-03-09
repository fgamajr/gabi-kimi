import type { Page, Route } from "@playwright/test";

interface SessionPayload {
  authenticated: boolean;
  principal?: {
    label?: string;
    source?: string;
    user_id?: string;
    roles?: string[];
    email?: string;
    status?: string;
  };
  expires_in_sec?: number;
}

interface SearchRecord {
  query: string;
  section?: string;
  results: Array<Record<string, unknown>>;
}

interface MockApiOptions {
  session?: "visitor" | "admin";
  topSearches?: Array<{ term: string; count: number }>;
  highlights?: Array<Record<string, unknown>>;
  searchRecords?: SearchRecord[];
  uploadResult?: { job_id: string; status: string };
}

const DEFAULT_ANALYTICS = {
  overview: {
    total_documents: 1200,
    total_organs: 42,
    total_types: 19,
    date_min: "2024-01-01",
    date_max: "2026-03-08",
    tracked_months: 24,
  },
  section_totals: [],
  section_monthly: [],
  top_types_monthly: {
    months: [],
    series: [],
  },
  top_organs: [],
  latest_documents: [],
};

const DEFAULT_TOP_SEARCHES = [
  { term: "licitação", count: 32 },
  { term: "energia solar", count: 18 },
  { term: "teletrabalho", count: 11 },
];

const DEFAULT_HIGHLIGHTS = [
  {
    id: "doc-licitacao-integrada",
    title: "Portaria de Licitação Integrada",
    snippet: "Atualiza o fluxo de contratação integrada para projetos estratégicos.",
    issuing_organ: "Ministério da Gestão",
    art_type: "Portaria",
    pub_date: "2026-03-08",
    section: "do1",
    page: "14",
  },
  {
    id: "doc-energia-solar",
    title: "Programa Energia Solar em Escolas",
    snippet: "Institui metas trimestrais para adoção de energia solar em escolas federais.",
    issuing_organ: "Ministério da Educação",
    art_type: "Resolução",
    pub_date: "2026-03-07",
    section: "do2",
    page: "7",
  },
];

const DEFAULT_SEARCH_RECORDS: SearchRecord[] = [
  {
    query: "licitação",
    results: [
      {
        id: "doc-licitacao-integrada",
        title: "Portaria de Licitação Integrada",
        snippet: "Atualiza o fluxo de contratação integrada para projetos estratégicos.",
        pub_date: "2026-03-08",
        section: "do1",
        page_number: "14",
        art_type: "Portaria",
        issuing_organ: "Ministério da Gestão",
      },
      {
        id: "doc-licitacao-do2",
        title: "Aviso de Licitação para Infraestrutura Regional",
        snippet: "Abre seleção para obras com foco em modernização logística.",
        pub_date: "2026-03-06",
        section: "do2",
        page_number: "3",
        art_type: "Aviso",
        issuing_organ: "Ministério dos Transportes",
      },
    ],
  },
  {
    query: "licitação",
    section: "do2",
    results: [
      {
        id: "doc-licitacao-do2",
        title: "Aviso de Licitação para Infraestrutura Regional",
        snippet: "Abre seleção para obras com foco em modernização logística.",
        pub_date: "2026-03-06",
        section: "do2",
        page_number: "3",
        art_type: "Aviso",
        issuing_organ: "Ministério dos Transportes",
      },
    ],
  },
];

const DEFAULT_UPLOAD_RESULT = { job_id: "job-123", status: "queued" };

function buildSession(session: MockApiOptions["session"]): SessionPayload {
  if (session === "admin") {
    return {
      authenticated: true,
      principal: {
        label: "Operacao GABI",
        source: "session",
        user_id: "admin-001",
        roles: ["admin", "user"],
        email: "operacao@gabi.local",
        status: "active",
      },
      expires_in_sec: 3600,
    };
  }

  return { authenticated: false, expires_in_sec: 3600 };
}

function json(route: Route, body: unknown, status = 200) {
  return route.fulfill({
    status,
    contentType: "application/json; charset=utf-8",
    body: JSON.stringify(body),
  });
}

export async function installApiMocks(page: Page, options: MockApiOptions = {}) {
  const topSearches = options.topSearches ?? DEFAULT_TOP_SEARCHES;
  const highlights = options.highlights ?? DEFAULT_HIGHLIGHTS;
  const searchRecords = options.searchRecords ?? DEFAULT_SEARCH_RECORDS;
  const uploadResult = options.uploadResult ?? DEFAULT_UPLOAD_RESULT;

  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const query = url.searchParams.get("q") ?? "";
    const section = (url.searchParams.get("section") ?? "").toLowerCase() || undefined;

    if (request.method() === "GET" && url.pathname === "/api/auth/session") {
      return json(route, buildSession(options.session));
    }

    if (request.method() === "GET" && url.pathname === "/api/analytics") {
      return json(route, DEFAULT_ANALYTICS);
    }

    if (request.method() === "GET" && url.pathname === "/api/top-searches") {
      return json(route, { items: topSearches });
    }

    if (request.method() === "GET" && url.pathname === "/api/highlights") {
      return json(route, { items: highlights });
    }

    if (request.method() === "GET" && url.pathname === "/api/search") {
      const record = searchRecords.find(
        (candidate) =>
          candidate.query.toLowerCase() === query.toLowerCase() &&
          (candidate.section ?? "") === (section ?? ""),
      );

      return json(route, {
        results: record?.results ?? [],
        total: record?.results.length ?? 0,
        page: 1,
        page_size: 20,
        query,
      });
    }

    if (request.method() === "POST" && url.pathname === "/api/admin/upload") {
      return json(route, uploadResult);
    }

    return json(
      route,
      {
        detail: `Unhandled mocked API request: ${request.method()} ${url.pathname}${url.search}`,
      },
      501,
    );
  });
}
