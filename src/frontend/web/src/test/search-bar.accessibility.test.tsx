import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { SearchBar } from "@/components/SearchBar";
import { expectNamedInteractiveElements } from "@/test/a11y";

vi.mock("@/hooks/useI18n", () => ({
  useI18n: () => ({
    locale: "pt-BR",
    setLocale: vi.fn(),
    t: (key: string) =>
      ({
        "searchBar.ariaLabel": "Buscar documentos no Diário Oficial",
        "searchBar.clear": "Limpar pesquisa",
        "searchBar.placeholder": "Buscar no Diário Oficial...",
        "searchBar.status.searching": "Buscando no acervo",
        "searchBar.status.settled": "Resultados prontos",
        "searchBar.status.typing": "Lapidando consulta",
      })[key] ?? key,
  }),
}));

describe("SearchBar accessibility", () => {
  it("exposes the search field through its accessible label", () => {
    render(
      <MemoryRouter>
        <SearchBar />
      </MemoryRouter>,
    );

    expect(
      screen.getByRole("combobox", { name: "Buscar documentos no Diário Oficial" }),
    ).toBeInTheDocument();
  });

  it("clears the query, preserves focus, and keeps the clear button named", () => {
    const onQueryChange = vi.fn();

    const { container } = render(
      <MemoryRouter>
        <SearchBar defaultValue="portaria" onQueryChange={onQueryChange} showShortcutHint={false} />
      </MemoryRouter>,
    );

    const input = screen.getByRole("combobox", { name: "Buscar documentos no Diário Oficial" });
    const clearButton = screen.getByRole("button", { name: "Limpar pesquisa" });

    expectNamedInteractiveElements(container);
    expect(input).toHaveValue("portaria");

    fireEvent.click(clearButton);

    expect(onQueryChange).toHaveBeenCalledWith("");
    expect(input).toHaveValue("");
    expect(input).toHaveFocus();
    expect(screen.queryByRole("button", { name: "Limpar pesquisa" })).not.toBeInTheDocument();
  });
});
