# Run this when you have the Docker in your system or want to use docker 
# If you don't want to use the Docker then install the redis-server
# 1. Update - sudo apt update
# 2. Install - sudo apt install redis-server
# 3. Restart - sudo systemctl restart redis-server
# 4. Enable and start - sudo systemctl enable redis-server && sudo systemctl start redis-server
# 5. Status - sudo systemctl status redis-server
# 6. Check - `redis-cli` in your terminal.
prepare: 
	docker run --name redis -p 6379:6379 redis:7.0.4

.PHONY: prepare