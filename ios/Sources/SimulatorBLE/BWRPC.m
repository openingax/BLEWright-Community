#import "BWRPC.h"
#import "BWProtocol.generated.h"
#import "include/SimulatorBLE.h"
#if TARGET_OS_SIMULATOR && DEBUG
#import <Network/Network.h>
static uint16_t BWConfiguredPort = 0;
void BWSimulatorBLESetPort(uint16_t port) { @synchronized(BWRPC.class) { BWConfiguredPort = port; } }
@interface BWRPC ()
@property(nonatomic) nw_connection_t connection;
@property(nonatomic, copy) NSString *port;
@property(nonatomic) dispatch_queue_t queue;
@property(atomic) BOOL ready;
@property(nonatomic) BOOL ended;
@property(nonatomic) NSString *session;
@property(nonatomic) NSMutableData *buffer;
@property(nonatomic) NSMutableDictionary<NSNumber *, BWResult> *pending;
@property(nonatomic) NSUInteger sequence;
@property(nonatomic) dispatch_source_t heartbeat;
@end
@implementation BWRPC
- (instancetype)init {
    if ((self = [super init])) {
        _queue = dispatch_queue_create("space.nomoloop.blewright.rpc", DISPATCH_QUEUE_SERIAL);
        _buffer = [NSMutableData data];
        _pending = [NSMutableDictionary dictionary];
        @synchronized(BWRPC.class) {
            _port = BWConfiguredPort ? [@(BWConfiguredPort) stringValue] :
                (NSProcessInfo.processInfo.environment[@"BLEWRIGHT_PORT"] ?: [@(BW_RPC_PORT) stringValue]);
        }
    }
    return self;
}
- (void)start {
    dispatch_async(_queue, ^{

      self.connection = nw_connection_create(
          nw_endpoint_create_host("127.0.0.1", self.port.UTF8String),
          nw_parameters_create_secure_tcp(NW_PARAMETERS_DISABLE_PROTOCOL,
                                          NW_PARAMETERS_DEFAULT_CONFIGURATION));
      nw_connection_set_queue(self.connection, self.queue);
      __weak BWRPC *weak = self;
      nw_connection_set_state_changed_handler(
          self.connection, ^(nw_connection_state_t state, nw_error_t error) {
            BWRPC *s = weak;
            if (!s)
                return;
            if (state == nw_connection_state_ready)
                [s receive];
            else if (state == nw_connection_state_failed || state == nw_connection_state_waiting)
                [s fail:@"RPC connection unavailable"];
          });
      nw_connection_start(self.connection);
      dispatch_after(dispatch_time(DISPATCH_TIME_NOW, BW_RPC_TIMEOUT_MS * NSEC_PER_MSEC),
                     self.queue, ^{
                       if (!weak.ready)
                           [weak fail:@"RPC handshake timeout"];
                     });
    });
}
- (void)receive {
    if (_ended)
        return;
    __weak BWRPC *weak = self;
    nw_connection_receive(
        _connection, 1, BW_RPC_MAX_FRAME,
        ^(dispatch_data_t content, nw_content_context_t context, bool complete, nw_error_t error) {
          BWRPC *s = weak;
          if (!s || s.ended)
              return;
          if (content) {
              dispatch_data_apply(content, ^bool(dispatch_data_t region, size_t offset,
                                                 const void *bytes, size_t size) {
                [s.buffer appendBytes:bytes length:size];
                return true;
              });
              [s consume];
          }
          if (error || complete) {
              [s fail:@"RPC service disconnected"];
              return;
          }
          [s receive];
        });
}
- (void)consume {
    while (!_ended) {
        const uint8_t *bytes = _buffer.bytes;
        NSUInteger length = _buffer.length, index = 0;
        while (index < length && bytes[index] != '\n')
            index++;
        if (index > BW_RPC_MAX_FRAME) {
            [self fail:@"RPC frame too large"];
            return;
        }
        if (index == length)
            return;
        NSData *line = [_buffer subdataWithRange:NSMakeRange(0, index)];
        [_buffer replaceBytesInRange:NSMakeRange(0, index + 1) withBytes:NULL length:0];
        NSDictionary *f = [NSJSONSerialization JSONObjectWithData:line options:0 error:nil];
        if (![f isKindOfClass:NSDictionary.class] ||
            [f[@"version"] integerValue] != BW_RPC_VERSION) {
            [self fail:@"RPC protocol mismatch"];
            return;
        }
        if (!_session) {
            if (![f[@"type"] isEqual:@"hello"] || ![f[@"sessionId"] isKindOfClass:NSString.class]) {
                [self fail:@"Missing RPC hello"];
                return;
            }
            _session = f[@"sessionId"];
            _ready = YES;
            __weak BWRPC *weak = self;
            _heartbeat = dispatch_source_create(DISPATCH_SOURCE_TYPE_TIMER, 0, 0, _queue);
            dispatch_source_set_timer(
                _heartbeat, dispatch_time(DISPATCH_TIME_NOW, BW_RPC_HEARTBEAT_MS * NSEC_PER_MSEC),
                BW_RPC_HEARTBEAT_MS * NSEC_PER_MSEC, 10 * NSEC_PER_MSEC);
            dispatch_source_set_event_handler(_heartbeat, ^{
              [weak request:@"ping"
                      params:@{}
                  completion:^(NSDictionary *r, NSError *e){
                  }];
            });
            dispatch_resume(_heartbeat);
            if (_onReady)
                _onReady();
            continue;
        }
        if (![f[@"sessionId"] isEqual:_session]) {
            [self fail:@"RPC session mismatch"];
            return;
        }
        if ([f[@"type"] isEqual:@"result"]) {
            BWResult done = _pending[f[@"id"]];
            [_pending removeObjectForKey:f[@"id"]];
            if (done) {
                NSError *e =
                    f[@"error"]
                        ? [NSError errorWithDomain:@"BLEWrightRPC"
                                              code:1
                                          userInfo:@{
                                              NSLocalizedDescriptionKey : [f[@"error"] description]
                                          }]
                        : nil;
                done(f[@"result"], e);
            }
        } else if ([f[@"type"] isEqual:@"event"] && _onEvent)
            _onEvent(f);
    }
}
- (void)request:(NSString *)method params:(NSDictionary *)params completion:(BWResult)completion {
    // Owner dispatches all operations onto this serial queue.
    if (!_ready || _ended) {
        completion(nil,
                   [NSError errorWithDomain:@"BLEWrightRPC"
                                       code:2
                                   userInfo:@{NSLocalizedDescriptionKey : @"RPC not connected"}]);
        return;
    }
    NSNumber *ident = @(++_sequence);
    _pending[ident] = [completion copy];
    NSDictionary *f = @{
        @"version" : @(BW_RPC_VERSION),
        @"sessionId" : _session,
        @"id" : ident,
        @"method" : method,
        @"params" : params
    };
    NSMutableData *data = [[NSJSONSerialization dataWithJSONObject:f options:0
                                                             error:nil] mutableCopy];
    [data appendBytes:"\n" length:1];
    dispatch_data_t payload = dispatch_data_create(data.bytes, data.length, _queue, ^{
      (void)data;
    });
    __weak BWRPC *weak = self;
    nw_connection_send(_connection, payload, NW_CONNECTION_DEFAULT_MESSAGE_CONTEXT, true,
                       ^(nw_error_t error) {
                         if (error)
                             [weak fail:@"RPC write failed"];
                       });
    int64_t timeout = [method isEqualToString:@"connect"] ? BW_RPC_CONNECT_TIMEOUT_MS
        : [method isEqualToString:@"discover"] ? BW_RPC_DISCOVER_TIMEOUT_MS
        : [method isEqualToString:@"session.end"] ? BW_RPC_END_SESSION_TIMEOUT_MS
        : BW_RPC_TIMEOUT_MS;
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW, timeout * NSEC_PER_MSEC), _queue, ^{
      if (weak.pending[ident])
          [weak fail:[@"RPC timeout: " stringByAppendingString:method]];
    });
}
- (void)fail:(NSString *)reason {
    if (_ended)
        return;
    _ended = YES;
    _ready = NO;
    [_pending removeAllObjects];
    if (_heartbeat) {
        dispatch_source_cancel(_heartbeat);
        _heartbeat = nil;
    }
    if (_connection)
        nw_connection_cancel(_connection);
    if (_onClose)
        _onClose([NSError errorWithDomain:@"BLEWrightRPC"
                                     code:3
                                 userInfo:@{NSLocalizedDescriptionKey : reason}]);
}
- (void)endSession:(void (^)(NSError *))completion {
    dispatch_async(_queue, ^{
      // Resolve once on either acknowledged cleanup or transport failure/timeout.
      __block BOOL completed = NO;
      void (^finish)(NSError *) = ^(NSError *error) {
        if (completed) return;
        completed = YES;
        self.onClose = nil;
        self.onReady = nil;
        self.onEvent = nil;
        [self fail:@"Session ended"];
        dispatch_async(dispatch_get_main_queue(), ^{ completion(error); });
      };
      self.onClose = finish;
      if (self.ended || !self.ready) { finish(nil); return; }
      [self request:@"session.end" params:@{} completion:^(NSDictionary *result, NSError *error) {
        finish(error);
      }];
    });
}
- (void)stop {
    dispatch_async(_queue, ^{
      self.onClose = nil;
      [self fail:@"Closed"];
    });
}
- (void)dealloc {
    if (_heartbeat)
        dispatch_source_cancel(_heartbeat);
    if (_connection)
        nw_connection_cancel(_connection);
}
@end
#endif
