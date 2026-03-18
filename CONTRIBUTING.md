# Contributing to vizpath

Thank you for your interest in contributing to vizpath. This document provides guidelines and instructions for contributing.

## Getting Started

### Prerequisites

- Python 3.10+
- Node.js 20+
- Docker and Docker Compose

### Local Development Setup

1. Clone the repository:
```bash
git clone https://github.com/yourusername/vizpath.git
cd vizpath
```

2. Copy and inspect environment:
```bash
cp .env.example .env
```

3. Bootstrap dependencies:
```bash
make bootstrap
```

4. Start local services:
```bash
docker-compose up -d postgres redis
```

5. Start API server and dashboard in separate terminals:
```bash
make dev-server    # terminal 1
make dev-dashboard # terminal 2
```

6. Optional: use `./demo.sh` for end-to-end startup with one command.

Optional: run pre-commit checks locally:

```bash
pip install pre-commit
pre-commit install
pre-commit run --all-files
```

## Development Workflow

### Branching Strategy

- `main` - Production-ready code
- `feature/*` - New features
- `fix/*` - Bug fixes
- `docs/*` - Documentation updates

### Making Changes

1. Create a branch from `main`:
   ```bash
   git checkout -b feature/your-feature-name
   ```

2. Make your changes following the code style guidelines

3. Write or update tests as needed

4. Commit your changes with a descriptive message:
   ```bash
   git commit -m "feat(scope): add new feature"
   ```

### Commit Message Format

We follow the [Conventional Commits](https://www.conventionalcommits.org/) specification:

```
type(scope): description

[optional body]
```

Types:
- `feat` - New feature
- `fix` - Bug fix
- `docs` - Documentation
- `style` - Code style (formatting, etc.)
- `refactor` - Code refactoring
- `perf` - Performance improvement
- `test` - Tests
- `chore` - Maintenance tasks

### Code Style

**Python (SDK & Server):**
- Use [Black](https://github.com/psf/black) for formatting
- Use [Ruff](https://github.com/astral-sh/ruff) for linting
- Add type hints to all functions
- Write docstrings for public APIs

**TypeScript (Dashboard):**
- Use ESLint and Prettier
- Use TypeScript strict mode
- Document component props with JSDoc

### Running Tests

```bash
# SDK tests
cd sdk && pytest

# Server tests
cd server && pytest

# Dashboard tests
cd dashboard && npm test
```

For CI parity:

```bash
make ci-check
make test-sdk
make test-server
make lint
```

When adding code that changes API responses, include/update tests in the relevant package.

## Pull Request Process

1. Ensure all tests pass
2. Update documentation if needed
3. Create a pull request with a clear description
4. Wait for review and address any feedback

## Reporting Issues

When reporting issues, please include:

- A clear description of the problem
- Steps to reproduce
- Expected vs actual behavior
- Environment details (OS, Python version, etc.)

## Questions?

Feel free to open an issue for questions or join discussions in existing issues.

## License

By contributing, you agree that your contributions will be licensed under the Apache 2.0 License.
