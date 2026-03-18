from dataclasses import dataclass, field


@dataclass
class JobResult:
    success: bool
    message: str
    warnings: list[str] = field(default_factory=list)
    generated_files: list[str] = field(default_factory=list)
    log_file: str | None = None
