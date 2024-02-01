prepare: 
	docker run --name redis -p 6379:6379 redis:7.0.4

.PHONY: prepare