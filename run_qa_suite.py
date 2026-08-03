import subprocess
import sys
import os
import time

try:
    sys.stdout.reconfigure(encoding='utf-8')
except AttributeError:
    pass

def print_header(title):
    print("\n" + "="*60)
    print(f"🚀 {title.upper()}")
    print("="*60)

def run_backend_tests():
    print_header("Executando Suite de Testes do Backend (Pytest)")
    
    # Decide which pytest to use (venv or global)
    pytest_path = os.path.join("backend", ".venv", "Scripts", "pytest")
    if not os.path.exists(pytest_path):
        pytest_path = "pytest" # fallback
        
    try:
        # Run tests in the backend directory
        result = subprocess.run(
            [pytest_path, "tests/"], 
            cwd="backend",
            check=False,
            text=True
        )
        return result.returncode == 0
    except FileNotFoundError:
        print("⚠️ Pytest não encontrado no ambiente. Pulando testes do backend.")
        return False

def run_frontend_tests():
    print_header("Executando Suite de Testes E2E (Playwright)")
    try:
        # npx playwright test
        result = subprocess.run(
            ["npx", "playwright", "test"], 
            check=False,
            text=True,
            shell=True # Required on Windows for npx
        )
        return result.returncode == 0
    except FileNotFoundError:
        print("⚠️ Playwright não encontrado. Execute 'npm install' primeiro.")
        return False

def main():
    print_header("Landscape Metrics Extractor - QA Automations")
    print("Iniciando a execução centralizada da Suite de Testes...")
    time.sleep(1)
    
    backend_ok = run_backend_tests()
    frontend_ok = run_frontend_tests()
    
    print_header("Relatório Final de Qualidade (QA)")
    if backend_ok and frontend_ok:
        print("✅ SUCESSO: Todos os testes passaram sem problemas.")
        print("O sistema está validado e pronto para deploy.")
        sys.exit(0)
    else:
        print("❌ FALHA: Foram encontrados erros na execução.")
        if not backend_ok:
            print(" - Backend (Pytest): FALHOU")
        if not frontend_ok:
            print(" - Frontend (Playwright): FALHOU")
        sys.exit(1)

if __name__ == "__main__":
    main()
