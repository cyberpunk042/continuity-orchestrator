# Examples

Ready-to-use configurations for common use cases.

## Available Examples

| Example | Description |
|---------|-------------|
| [minimal/](minimal/) | Bare minimum to run — just 3 rules |
| [deadman-switch/](deadman-switch/) | Classic deadman switch with notifications |
| [newsletter/](newsletter/) | Scheduled content publishing |

## How to Use

1. Copy an example to your project root:
   ```bash
   cp -r examples/deadman-switch/* .
   ```

2. Configure credentials:
   ```bash
   cp .env.example .env
   # Edit .env with your API keys
   ```

3. Initialize:
   ```bash
   python -m src.main init --project "my-project"
   ```

4. Run:
   ```bash
   python -m src.main tick
   ```

## Creating Your Own

Start with `minimal/` and add:
- More rules in `policy/rules.yaml`
- More actions in `policy/plans/`
- Custom templates in `templates/`
