local key = KEYS[1]
local refill_rate = tonumber(ARGV[1])
local capacity = tonumber(ARGV[2])
local timestamp = tonumber(ARGV[3])
local token_value = tonumber(ARGV[4])

local token = redis.call('HGET',key,'token')

if token == false then
    token = capacity
    redis.call('HSET',key,'token',token)
else
    token = tonumber(token)
end

local last_read_timestamp = redis.call('HGET',key,'last_read_timestamp')

if last_read_timestamp == false then
    last_read_timestamp = timestamp
    redis.call('HSET',key,'last_read_timestamp',last_read_timestamp)
else
    last_read_timestamp = tonumber(last_read_timestamp)
end

local interval = timestamp - last_read_timestamp

local refill_amount = interval * refill_rate

if token + refill_amount >= capacity then
    token = capacity
else 
    token = token + refill_amount
end

redis.call('HSET',key,'last_read_timestamp',timestamp)

local allowed
if token >= token_value then
    allowed = 1
    token = token - token_value
    redis.call('HSET',key,"token",token)
else
    allowed = 0
end

local gap = capacity - token
local reset
if refill_rate > 0 then
    reset = gap / refill_rate
else
    reset = -1
end

return {allowed, capacity, token, reset}



