# Zero-Kelvin System Tests

Testes de sistema (harness) para experimentos de pipeline em escala. O harness C# (`Gabi.ZeroKelvinHarness`) orquestra ambiente (Testcontainers), API (WebApplicationFactory), pipeline e métricas; o xUnit (`Gabi.System.Tests`) apenas chama o harness e faz asserções nos resultados.

## Execução

- **Todos os testes da solution (exceto System):**  
  `dotnet test GabiSync.sln --filter "Category!=System"`

- **Apenas system tests:**  
  `dotnet test tests/System/Gabi.System.Tests --filter "Category=System"`

O CI rápido deve usar o filtro `Category!=System`. O CI dedicado para system tests usa o segundo comando.
