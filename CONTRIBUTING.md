# Contributing to ExamShield

First off, thank you for considering contributing to ExamShield! 🎉

It's people like you that make ExamShield such a great tool for promoting academic integrity.

## 📋 Table of Contents

- [Code of Conduct](#code-of-conduct)
- [How Can I Contribute?](#how-can-i-contribute)
- [Development Setup](#development-setup)
- [Pull Request Process](#pull-request-process)
- [Coding Standards](#coding-standards)
- [Commit Message Guidelines](#commit-message-guidelines)

---

## Code of Conduct

This project adheres to a Code of Conduct. By participating, you are expected to uphold this code.

- Be respectful and inclusive
- Welcome newcomers and help them learn
- Focus on what is best for the community
- Show empathy towards other community members

---

## How Can I Contribute?

### 🐛 Reporting Bugs

Before creating bug reports, please check the existing issues. When creating a bug report, include as many details as possible:

- **Use a clear and descriptive title**
- **Describe the exact steps to reproduce the problem**
- **Provide specific examples**
- **Describe the behavior you observed and what you expected**
- **Include screenshots if applicable**
- **Provide your environment details** (OS, Python version, GPU, etc.)

Use the [Bug Report Template](.github/ISSUE_TEMPLATE/bug_report.md)

### 💡 Suggesting Enhancements

Enhancement suggestions are tracked as GitHub issues. When creating an enhancement suggestion:

- **Use a clear and descriptive title**
- **Provide a step-by-step description of the suggested enhancement**
- **Explain why this enhancement would be useful**
- **List some examples of where this enhancement could be used**

Use the [Feature Request Template](.github/ISSUE_TEMPLATE/feature_request.md)

### 📝 Improving Documentation

Documentation improvements are always welcome! This includes:

- Fixing typos or clarifying existing documentation
- Adding examples or tutorials
- Translating documentation
- Creating video tutorials or guides

### 💻 Code Contributions

1. **Fork the repository**
2. **Create a branch** (`git checkout -b feature/AmazingFeature`)
3. **Make your changes**
4. **Test your changes thoroughly**
5. **Commit your changes** (see commit guidelines below)
6. **Push to your fork** (`git push origin feature/AmazingFeature`)
7. **Open a Pull Request**

---

## Development Setup

### Prerequisites

- Python 3.8 or higher
- pip (Python package manager)
- Git
- (Optional) NVIDIA GPU with CUDA for faster processing

### Setup Steps

```bash
# 1. Clone your fork
git clone https://github.com/MORSHEDMDMONOARUL/ExamShield.git
cd ExamShield

# 2. Add upstream remote
git remote add upstream https://github.com/OriginalAuthor/ExamShield.git

# 3. Create virtual environment
python -m venv .venv

# 4. Activate virtual environment
# Windows
.venv\Scripts\activate
# Linux/Mac
source .venv/bin/activate

# 5. Install dependencies
pip install -r requirements.txt

# 6. Install development dependencies
pip install pytest black flake8 mypy

# 7. Run tests
pytest tests/

# 8. Run linter
flake8 src/
```

---

## Pull Request Process

### Before Submitting

- [ ] Code follows the project's coding standards
- [ ] All tests pass
- [ ] Documentation is updated  (if applicable)
- [ ] Commit messages follow guidelines
- [ ] Branch is up to date with main

### PR Checklist

```markdown
## Description
[Clear description of what this PR does]

## Type of Change
- [ ] Bug fix (non-breaking change)
- [ ] New feature (non-breaking change)
- [ ] Breaking change
- [ ] Documentation update

## Testing
- [ ] Tested locally
- [ ] Added/updated tests
- [ ] All tests pass

## Screenshots (if applicable)
[Add screenshots here]

## Additional Notes
[Any additional information]
```

### Review Process

1. Maintainers will review your PR
2. Address any requested changes
3. Once approved, a maintainer will merge your PR
4. Your contribution will be included in the next release!

---

## Coding Standards

### Python Style Guide

- **Follow PEP 8** - Python's official style guide
- **Use meaningful variable names** - `student_count` not `sc`
- **Add docstrings** - Document all classes and functions
- **Type hints** - Use type hints where appropriate
- **Keep functions focused** - One function, one purpose

### Example

```python
def calculate_risk_score(detections: List[Dict], weights: Dict[str, float]) -> float:
    """
    Calculate overall risk score based on weighted detections.
    
    Args:
        detections: List of detection dictionaries
        weights: Dictionary mapping class names to weight values
    
    Returns:
        float: Risk score from 0.0 to 100.0
    
    Example:
        >>> detections = [{'class': 'phone', 'confidence': 0.85}]
        >>> weights = {'phone': 3.0}
        >>> calculate_risk_score(detections, weights)
        85.0
    """
    # Implementation here
    pass
```

### Code Formatting

```bash
# Format code with Black
black src/

# Check code quality
flake8 src/

# Type checking
mypy src/
```

---

## Commit Message Guidelines

### Format

```
<type>(<scope>): <subject>

<body>

<footer>
```

### Types

- **feat**: New feature
- **fix**: Bug fix
- **docs**: Documentation changes
- **style**: Code style changes (formatting, etc.)
- **refactor**: Code refactoring
- **test**: Adding or updating tests
- **chore**: Maintenance tasks

### Examples

```
feat(detection): add facial recognition support

Implemented facial recognition using FaceNet model
to identify students during exam monitoring.

Closes #123
```

```
fix(alert): resolve photo capture timing issue

Fixed bug where photos were captured before
alert cooldown period expired.

Fixes #456
```

---

## Additional Resources

- [Python Style Guide (PEP 8)](https://www.python.org/dev/peps/pep-0008/)
- [How to Write a Git Commit Message](https://chris.beams.io/posts/git-commit/)
- [GitHub Flow Guide](https://guides.github.com/introduction/flow/)

---

## Recognition

Contributors will be recognized in:
- README.md Contributors section
- Release notes
- GitHub contributors page

Thank you for contributing to ExamShield! 🚀

