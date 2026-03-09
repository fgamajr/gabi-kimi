import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import AppShell from "@/components/layout/AppShell";
import { expectNamedInteractiveElements } from "@/test/a11y";

const mockUseAuth = vi.fn();
const mockUseTheme = vi.fn();

vi.mock("@/hooks/useI18n", () => ({
  useI18n: () => ({
    locale: "pt-BR",
    setLocale: vi.fn(),
    t: (key: string) =>
      ({
        "appShell.skipToMain": "Pular para conteúdo principal",
        "appShell.nav.home": "Home",
        "appShell.nav.search": "Busca",
        "appShell.nav.analytics": "Analytics",
        "appShell.nav.chat": "Chat",
        "appShell.nav.favorites": "Favoritos",
        "common.actions.login": "Entrar",
        "appShell.account.openDarkMode": "Modo escuro",
      })[key] ?? key,
  }),
}));

vi.mock("@/hooks/useAuth", () => ({
  useAuth: () => mockUseAuth(),
}));

vi.mock("@/hooks/useTheme", () => ({
  useTheme: () => mockUseTheme(),
}));

function renderAppShell(initialEntries = ["/"]) {
  return render(
    <MemoryRouter initialEntries={initialEntries}>
      <Routes>
        <Route path="/" element={<AppShell />}>
          <Route index element={<h1>Home</h1>} />
          <Route path="busca" element={<h1>Busca</h1>} />
          <Route path="analytics" element={<h1>Analytics</h1>} />
          <Route path="chat" element={<h1>Chat</h1>} />
          <Route path="favoritos" element={<h1>Favoritos</h1>} />
          <Route path="login" element={<h1>Login</h1>} />
          <Route path="perfil" element={<h1>Perfil</h1>} />
          <Route path="configuracoes" element={<h1>Configuracoes</h1>} />
          <Route path="admin/upload" element={<h1>Upload</h1>} />
          <Route path="admin/jobs" element={<h1>Jobs</h1>} />
          <Route path="admin/users" element={<h1>Operacao</h1>} />
        </Route>
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  mockUseAuth.mockReturnValue({
    user: null,
    role: "visitor",
    isAdmin: false,
    logout: vi.fn(),
  });
  mockUseTheme.mockReturnValue({
    theme: "light",
    toggleTheme: vi.fn(),
  });
  vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => {
    callback(0);
    return 1;
  });
  vi.stubGlobal("cancelAnimationFrame", vi.fn());
});

describe("AppShell accessibility", () => {
  it("renders a skip link and main landmark for keyboard navigation", () => {
    const { container } = renderAppShell();

    const skipLink = screen.getByRole("link", { name: "Pular para conteúdo principal" });
    const main = screen.getByRole("main");

    expect(skipLink).toHaveAttribute("href", "#main-content");
    expect(main).toHaveAttribute("id", "main-content");
    expect(main).toHaveAttribute("tabindex", "-1");
    expectNamedInteractiveElements(container);
  });

  it("moves focus to the main landmark after route navigation", async () => {
    renderAppShell();

    const main = screen.getByRole("main");
    const buscaLink = screen.getAllByRole("link", { name: "Busca" })[0];

    fireEvent.click(buscaLink);

    await screen.findByRole("heading", { name: "Busca" });
    await waitFor(() => expect(main).toHaveFocus());
  });
});
