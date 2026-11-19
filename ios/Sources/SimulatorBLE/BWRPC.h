#import <Foundation/Foundation.h>
#import <TargetConditionals.h>
#if TARGET_OS_SIMULATOR && DEBUG
NS_ASSUME_NONNULL_BEGIN
typedef void (^BWResult)(NSDictionary *_Nullable, NSError *_Nullable);
@interface BWRPC : NSObject
@property(nonatomic, readonly) dispatch_queue_t queue;
@property(atomic, readonly) BOOL ready;
@property(nonatomic, copy, nullable) void (^onReady)(void);
@property(nonatomic, copy, nullable) void (^onEvent)(NSDictionary *);
@property(nonatomic, copy, nullable) void (^onClose)(NSError *);
- (void)start;
- (void)request:(NSString *)method params:(NSDictionary *)params completion:(BWResult)completion;
- (void)stop;
- (void)endSession:(void (^)(NSError *error))completion;
@end
NS_ASSUME_NONNULL_END
#endif
