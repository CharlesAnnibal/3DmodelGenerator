.PHONY: run help

run:
	model-factory

help:
	@echo "Available targets:"
	@echo "  make run       - Run model-factory with default settings"
	@echo "  make help      - Show this help message"
	@echo ""
	@echo "For more options, use: model-factory --help"
