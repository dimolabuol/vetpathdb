# Contributing to VetPathDB

Thank you for your interest in contributing to VetPathDB.

## Reporting Issues

If you encounter a bug or have a feature request, please
[open an issue](https://github.com/dimolabuol/vetpathdb/issues) with:

- A clear description of the problem or suggestion
- Steps to reproduce (for bugs)
- Your environment (OS, Python version, GPU availability)

## Development Setup

```bash
git clone https://github.com/dimolabuol/vetpathdb.git
cd vetpathdb
pip install -e ".[dev]"
```

## Running Tests

```bash
python -m pytest tests/ -v
```

## Submitting Changes

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/your-feature`)
3. Make your changes
4. Run the test suite
5. Submit a pull request with a clear description

## Code Style

- Follow PEP 8 conventions
- Use type hints for function signatures
- Add docstrings for public functions and classes

## License

By contributing, you agree that your contributions will be licensed
under the MIT License.
