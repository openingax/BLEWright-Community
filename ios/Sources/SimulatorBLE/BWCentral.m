#import "BWCentral.h"
#if TARGET_OS_SIMULATOR && DEBUG
static NSError *BWError(NSString *message) {
    return [NSError errorWithDomain:CBErrorDomain
                               code:CBErrorUnknown
                           userInfo:@{NSLocalizedDescriptionKey : message}];
}
static NSError *BWStatus(NSDictionary *r, NSError *e) {
    if (e)
        return e;
    NSInteger status = [r[@"status"] integerValue];
    return status
               ? [NSError errorWithDomain:status <= 17 ? CBATTErrorDomain : CBErrorDomain
                                     code:status <= 17 ? status : CBErrorUnknown
                                 userInfo:@{
                                     NSLocalizedDescriptionKey :
                                         [NSString stringWithFormat:@"BLE status %ld", (long)status]
                                 }]
               : nil;
}
static NSArray *BWBytes(NSData *d) {
    NSMutableArray *a = [NSMutableArray array];
    const uint8_t *b = d.bytes;
    for (NSUInteger i = 0; i < d.length; i++)
        [a addObject:@(b[i])];
    return a;
}
static NSData *BWData(NSArray *a) {
    NSMutableData *d = [NSMutableData data];
    for (NSNumber *n in a) {
        uint8_t b = n.unsignedCharValue;
        [d appendBytes:&b length:1];
    }
    return d;
}
static BOOL BWMatches(CBUUID *uuid, NSArray *filter) {
    return !filter || [filter containsObject:uuid];
}
@interface BWCentral ()
@property(nonatomic) NSMutableDictionary<NSString *, BWPeripheral *> *known;
@property(atomic, copy) NSString *scanID;
@property(nonatomic) NSArray *scanFilter;
@end
@implementation BWCentral
- (instancetype)initWithManager:(CBCentralManager *)m
                       delegate:(id<CBCentralManagerDelegate>)d
                          queue:(dispatch_queue_t)q {
    if ((self = [super init])) {
        _manager = m;
        _delegate = d;
        _callbackQueue = q ?: dispatch_get_main_queue();
        _known = [NSMutableDictionary dictionary];
        _state = CBManagerStateUnknown;
        _rpc = [BWRPC new];
        __weak BWCentral *weak = self;
        _rpc.onReady = ^{
          BWCentral *s = weak;
          s.state = CBManagerStatePoweredOn;
          [s updateState];
        };
        _rpc.onClose = ^(NSError *e) {
          [weak lost:e];
        };
        _rpc.onEvent = ^(NSDictionary *f) {
          [weak event:f];
        };
        [_rpc start];
    }
    return self;
}
- (void)updateState {
    dispatch_async(_callbackQueue, ^{
      id<CBCentralManagerDelegate> d = self.delegate;
      if ([d respondsToSelector:@selector(centralManagerDidUpdateState:)])
          [d centralManagerDidUpdateState:self.manager];
    });
}
- (void)emit:(BWPeripheral *)p
    selector:(SEL)selector
       block:(void (^)(id<CBPeripheralDelegate>))block {
    NSUInteger epoch = p.epoch;
    dispatch_async(_callbackQueue, ^{
      if (p.epoch != epoch)
          return;
      id<CBPeripheralDelegate> d = p.delegate;
      if ([d respondsToSelector:selector])
          block(d);
    });
}
- (void)lost:(NSError *)error {
    self.state = CBManagerStatePoweredOff;
    self.scanning = NO;
    self.scanID = nil;
    [self updateState];
    for (BWPeripheral *p in _known.allValues) {
        CBPeripheralState previous = p.state;
        p.epoch++;
        p.bwState = CBPeripheralStateDisconnected;
        p.bwCanSend = NO;
        p.busy = NO;
        [p.operations removeAllObjects];
        for (BWCharacteristic *c in p.characteristics.allValues)
            c.bwNotifying = NO;
        if (previous != CBPeripheralStateDisconnected) {
            dispatch_async(_callbackQueue, ^{
              id<CBCentralManagerDelegate> d = self.delegate;
              if (previous == CBPeripheralStateConnecting) {
                  if ([d respondsToSelector:@selector(centralManager:
                                                didFailToConnectPeripheral:error:)])
                      [d centralManager:self.manager didFailToConnectPeripheral:p error:error];
              } else if ([d respondsToSelector:@selector(centralManager:
                                                   didDisconnectPeripheral:error:)])
                  [d centralManager:self.manager didDisconnectPeripheral:p error:error];
            });
        }
    }
}
- (void)scan:(NSArray *)services options:(NSDictionary *)options {
    if (self.state != CBManagerStatePoweredOn)
        return;
    self.scanning = YES;
    dispatch_async(_rpc.queue, ^{
      if (self.scanID)
          [self.rpc request:@"scan.stop"
                     params:@{@"scanId" : self.scanID}
                 completion:^(NSDictionary *r, NSError *e){
                 }];
      self.scanID = NSUUID.UUID.UUIDString;
      self.scanFilter = [services copy];
      [self.rpc request:@"scan.start"
                 params:@{@"scanId" : self.scanID}
             completion:^(NSDictionary *r, NSError *e) {
               if (e) {
                   self.scanning = NO;
                   NSLog(@"SimulatorBLE scan: %@", e);
               }
             }];
    });
}
- (void)stopScan {
    self.scanning = NO;
    dispatch_async(_rpc.queue, ^{
      NSString *ident = self.scanID;
      self.scanID = nil;
      if (ident)
          [self.rpc request:@"scan.stop"
                     params:@{@"scanId" : ident}
                 completion:^(NSDictionary *r, NSError *e){
                 }];
    });
}
- (void)event:(NSDictionary *)f {
    if ([f[@"event"] isEqual:@"advertisement"]) {
        NSString *token = f[@"scanId"];
        if (!self.scanning || ![token isEqual:self.scanID])
            return;
        NSDictionary *device = f[@"device"];
        NSMutableArray *uuids = [NSMutableArray array];
        NSArray *raw = device[@"advertising"];
        for (NSUInteger i = 0; i < raw.count;) {
            NSUInteger n = [raw[i] unsignedIntegerValue];
            if (!n || i + n >= raw.count)
                break;
            NSUInteger type = [raw[i + 1] unsignedIntegerValue];
            if (type == 2 || type == 3) {
                for (NSUInteger j = i + 2; j + 1 <= i + n; j += 2) {
                    uint16_t v = [raw[j] unsignedIntValue] | ([raw[j + 1] unsignedIntValue] << 8);
                    [uuids
                        addObject:[CBUUID UUIDWithString:[NSString stringWithFormat:@"%04X", v]]];
                }
            }
            i += n + 1;
        }
        // Hardware backends normalize 16/32/128-bit UUIDs and merge scan responses.
        // Keep raw-AD fallback above for existing v1 mock peers.
        if ([device[@"serviceUUIDs"] isKindOfClass:NSArray.class]) {
            [uuids removeAllObjects];
            for (NSString *value in device[@"serviceUUIDs"])
                [uuids addObject:[CBUUID UUIDWithString:value]];
        }
        if (_scanFilter) {
            BOOL match = NO;
            for (CBUUID *u in uuids)
                if (BWMatches(u, _scanFilter))
                    match = YES;
            if (!match)
                return;
        }
        NSString *address = device[@"identity"] ?: device[@"address"];
        BWPeripheral *p = _known[address];
        if (!p) {
            p = [[BWPeripheral alloc] initBWWithAddress:address name:device[@"name"]];
            p.owner = self;
            p.address = device[@"address"];
            _known[address] = p;
        }
        if ([device[@"name"] length])
            p.bwName = device[@"name"];
        NSMutableDictionary *ad = [@{
            CBAdvertisementDataServiceUUIDsKey : uuids,
            CBAdvertisementDataIsConnectable : device[@"connectable"] ?: @YES
        } mutableCopy];
        if ([device[@"name"] length])
            ad[CBAdvertisementDataLocalNameKey] = device[@"name"];
        if (device[@"manufacturerData"])
            ad[CBAdvertisementDataManufacturerDataKey] = BWData(device[@"manufacturerData"]);
        if (device[@"txPower"])
            ad[CBAdvertisementDataTxPowerLevelKey] = device[@"txPower"];
        NSMutableDictionary *serviceData = [NSMutableDictionary dictionary];
        for (NSString *uuid in device[@"serviceData"])
            serviceData[[CBUUID UUIDWithString:uuid]] = BWData(device[@"serviceData"][uuid]);
        if (serviceData.count)
            ad[CBAdvertisementDataServiceDataKey] = serviceData;
        dispatch_async(_callbackQueue, ^{
          if (!self.scanning || ![token isEqual:self.scanID])
              return;
          id<CBCentralManagerDelegate> d = self.delegate;
          if ([d respondsToSelector:@selector(centralManager:
                                        didDiscoverPeripheral:advertisementData:RSSI:)])
              [d centralManager:self.manager
                  didDiscoverPeripheral:p
                      advertisementData:ad
                                   RSSI:device[@"rssi"]];
        });
    } else if ([f[@"event"] isEqual:@"disconnected"]) {
        for (BWPeripheral *p in _known.allValues) {
            if (![p.connectionID isEqual:f[@"connectionId"]] ||
                p.state == CBPeripheralStateDisconnected)
                continue;
            p.epoch++;
            NSUInteger epoch = p.epoch;
            p.bwState = CBPeripheralStateDisconnected;
            p.bwCanSend = NO;
            p.busy = NO;
            [p.operations removeAllObjects];
            for (BWCharacteristic *c in p.characteristics.allValues)
                c.bwNotifying = NO;
            NSError *error = [NSError errorWithDomain:CBErrorDomain
                                                 code:CBErrorUnknown
                                             userInfo:@{
                                                 NSLocalizedDescriptionKey : @"外设连接已断开",
                                                 @"BLEWrightReason" : f[@"reason"] ?: @0
                                             }];
            dispatch_async(_callbackQueue, ^{
              if (p.epoch != epoch)
                  return;
              id<CBCentralManagerDelegate> d = self.delegate;
              if ([d respondsToSelector:@selector(centralManager:didDisconnectPeripheral:error:)])
                  [d centralManager:self.manager didDisconnectPeripheral:p error:error];
            });
        }
    } else if ([f[@"event"] isEqual:@"notification"]) {
        for (BWPeripheral *p in _known.allValues) {
            if (![p.connectionID isEqual:f[@"connectionId"]] ||
                p.state != CBPeripheralStateConnected)
                continue;
            BWCharacteristic *c = p.characteristics[f[@"attributeId"]];
            if (!c.isNotifying)
                return;
            NSData *value = BWData(f[@"value"]);
            NSUInteger epoch = p.epoch;
            dispatch_async(_callbackQueue, ^{
              if (p.epoch != epoch || !c.isNotifying)
                  return;
              c.bwValue = value;
              id<CBPeripheralDelegate> d = p.delegate;
              if ([d respondsToSelector:@selector(peripheral:
                                            didUpdateValueForCharacteristic:error:)])
                  [d peripheral:p didUpdateValueForCharacteristic:c error:nil];
            });
        }
    }
}
- (void)connect:(BWPeripheral *)p {
    if (![p isKindOfClass:BWPeripheral.class] || p.owner != self)
        [NSException raise:NSInvalidArgumentException format:@"SimulatorBLE: unmanaged peripheral"];
    dispatch_async(_rpc.queue, ^{
      if (p.state != CBPeripheralStateDisconnected)
          return;
      p.epoch++;
      NSUInteger epoch = p.epoch;
      // Attribute IDs belong to one remote connection generation. Never reuse
      // cached IDs after reconnecting to real hardware.
      p.schema = nil;
      p.bwServices = nil;
      [p.allServices removeAllObjects];
      [p.characteristics removeAllObjects];
      [p.operations removeAllObjects];
      p.busy = NO;
      p.bwState = CBPeripheralStateConnecting;
      p.connectionID = NSUUID.UUID.UUIDString;
      [self.rpc request:@"connect"
                 params:@{@"connectionId" : p.connectionID, @"address" : p.address}
             completion:^(NSDictionary *r, NSError *e) {
               if (p.epoch != epoch || p.state != CBPeripheralStateConnecting)
                   return;
               NSError *error = BWStatus(r, e);
               p.attMTU = MAX(23, [r[@"mtu"] integerValue]);
               void (^finishConnect)(void) = ^{
                   if (p.epoch != epoch || p.state != CBPeripheralStateConnecting)
                       return;
                   p.bwState = error ? CBPeripheralStateDisconnected : CBPeripheralStateConnected;
                   p.bwCanSend = !error;
                   dispatch_async(self.callbackQueue, ^{
                     if (p.epoch != epoch)
                         return;
                     id<CBCentralManagerDelegate> d = self.delegate;
                     if (error) {
                         if ([d respondsToSelector:@selector(centralManager:
                                                       didFailToConnectPeripheral:error:)])
                             [d centralManager:self.manager didFailToConnectPeripheral:p error:error];
                     } else if ([d respondsToSelector:@selector(centralManager:didConnectPeripheral:)])
                         [d centralManager:self.manager didConnectPeripheral:p];
                   });
               };
               if (error) {
                   finishConnect();
                   return;
               }
               [self.rpc request:@"mtu"
                          params:@{@"connectionId" : p.connectionID, @"mtu" : @247}
                      completion:^(NSDictionary *result, NSError *mtuError) {
                        if (p.epoch != epoch || p.state != CBPeripheralStateConnecting)
                            return;
                        NSInteger mtu = [result[@"mtu"] integerValue];
                        if (!BWStatus(result, mtuError) && mtu >= 23 && mtu <= 517)
                            p.attMTU = mtu;
                        finishConnect();
                      }];
             }];
    });
}
- (void)cancel:(BWPeripheral *)p {
    dispatch_async(_rpc.queue, ^{
      if (p.owner != self || p.state == CBPeripheralStateDisconnected ||
          p.state == CBPeripheralStateDisconnecting)
          return;
      p.epoch++;
      NSUInteger epoch = p.epoch;
      p.bwState = CBPeripheralStateDisconnecting;
      p.bwCanSend = NO;
      p.busy = NO;
      [p.operations removeAllObjects];
      for (BWCharacteristic *c in p.characteristics.allValues)
          c.bwNotifying = NO;
      NSString *ident = p.connectionID;
      [self.rpc request:@"disconnect"
                 params:@{@"connectionId" : ident}
             completion:^(NSDictionary *r, NSError *e) {
               [self.rpc request:@"close"
                          params:@{@"connectionId" : ident}
                      completion:^(NSDictionary *r, NSError *e){
                      }];
               if (p.epoch != epoch)
                   return;
               p.bwState = CBPeripheralStateDisconnected;
               dispatch_async(self.callbackQueue, ^{
                 if (p.epoch != epoch)
                     return;
                 id<CBCentralManagerDelegate> d = self.delegate;
                 if ([d respondsToSelector:@selector(centralManager:
                                               didDisconnectPeripheral:error:)])
                     [d centralManager:self.manager didDisconnectPeripheral:p error:BWStatus(r, e)];
               });
             }];
    });
}
- (NSArray *)retrieve:(NSArray *)identifiers {
    __block NSMutableArray *matches = [NSMutableArray array];
    dispatch_sync(_rpc.queue, ^{
      for (BWPeripheral *p in self.known.allValues)
          if ([identifiers containsObject:p.identifier])
              [matches addObject:p];
    });
    return matches;
}
- (void)drain:(BWPeripheral *)p {
    if (p.busy || !p.operations.count)
        return;
    p.busy = YES;
    dispatch_block_t next = p.operations.firstObject;
    [p.operations removeObjectAtIndex:0];
    next();
}
- (void)perform:(BWPeripheral *)p work:(void (^)(BWResult))work done:(BWResult)done {
    dispatch_async(_rpc.queue, ^{
      if (p.owner != self || p.state != CBPeripheralStateConnected) {
          done(nil, BWError(@"Peripheral not connected"));
          return;
      }
      if (p.operations.count >= 32) {
          done(nil, BWError(@"Operation queue full"));
          return;
      }
      NSUInteger epoch = p.epoch;
      __weak BWPeripheral *weakPeripheral = p;
      [p.operations addObject:^{
        work(^(NSDictionary *r, NSError *e) {
          BWPeripheral *p = weakPeripheral;
          if (!p || p.epoch != epoch || p.state != CBPeripheralStateConnected)
              return;
          p.busy = NO;
          done(r, BWStatus(r, e));
          [self drain:p];
        });
      }];
      [self drain:p];
    });
}
- (void)operation:(BWPeripheral *)p
           method:(NSString *)method
           params:(NSDictionary *)params
             done:(BWResult)done {
    [self perform:p
             work:^(BWResult finish) {
               NSMutableDictionary *args = [params mutableCopy];
               args[@"connectionId"] = p.connectionID;
               [self.rpc request:method params:args completion:finish];
             }
             done:done];
}
- (void)discover:(BWPeripheral *)p services:(NSArray *)uuids {
    [self operation:p
             method:@"discover"
             params:@{}
               done:^(NSDictionary *r, NSError *e) {
                 if (!e) {
                     if (!p.schema) {
                         p.schema = r[@"services"];
                         for (NSDictionary *sd in p.schema) {
                             BWService *s = [[BWService alloc] initBWWithDefinition:sd
                                                                         peripheral:p];
                             NSMutableArray *chars = [NSMutableArray array];
                             for (NSDictionary *cd in sd[@"characteristics"]) {
                                 BWCharacteristic *c =
                                     [[BWCharacteristic alloc] initBWWithDefinition:cd service:s];
                                 NSMutableArray *ds = [NSMutableArray array];
                                 for (NSDictionary *dd in cd[@"descriptors"])
                                     [ds addObject:[[BWDescriptor alloc] initBWWithDefinition:dd
                                                                               characteristic:c]];
                                 c.allDescriptors = ds;
                                 p.characteristics[c.remoteID] = c;
                                 [chars addObject:c];
                             }
                             s.allCharacteristics = chars;
                             [p.allServices addObject:s];
                         }
                     }
                     NSMutableArray *a = [NSMutableArray array];
                     for (BWService *s in p.allServices)
                         if (BWMatches(s.UUID, uuids))
                             [a addObject:s];
                     p.bwServices = a;
                 }
                 [self emit:p
                     selector:@selector(peripheral:didDiscoverServices:)
                        block:^(id<CBPeripheralDelegate> d) {
                          [d peripheral:p didDiscoverServices:e];
                        }];
               }];
}
- (void)characteristics:(BWPeripheral *)p service:(BWService *)s filter:(NSArray *)uuids {
    dispatch_async(_rpc.queue, ^{
      NSMutableArray *a = [NSMutableArray array];
      for (BWCharacteristic *c in s.allCharacteristics)
          if (BWMatches(c.UUID, uuids))
              [a addObject:c];
      s.bwCharacteristics = a;
      [self emit:p
          selector:@selector(peripheral:didDiscoverCharacteristicsForService:error:)
             block:^(id<CBPeripheralDelegate> d) {
               [d peripheral:p didDiscoverCharacteristicsForService:s error:nil];
             }];
    });
}
- (void)descriptors:(BWPeripheral *)p characteristic:(BWCharacteristic *)c {
    dispatch_async(_rpc.queue, ^{
      c.bwDescriptors = c.allDescriptors;
      [self emit:p
          selector:@selector(peripheral:didDiscoverDescriptorsForCharacteristic:error:)
             block:^(id<CBPeripheralDelegate> d) {
               [d peripheral:p didDiscoverDescriptorsForCharacteristic:c error:nil];
             }];
    });
}
- (void)read:(BWPeripheral *)p characteristic:(BWCharacteristic *)c {
    [self operation:p
             method:@"read"
             params:@{@"attributeId" : c.remoteID}
               done:^(NSDictionary *r, NSError *e) {
                 NSData *v = e ? nil : BWData(r[@"value"]);
                 [self emit:p
                     selector:@selector(peripheral:didUpdateValueForCharacteristic:error:)
                        block:^(id<CBPeripheralDelegate> d) {
                          if (!e)
                              c.bwValue = v;
                          [d peripheral:p didUpdateValueForCharacteristic:c error:e];
                        }];
               }];
}
- (void)write:(BWPeripheral *)p
    characteristic:(BWCharacteristic *)c
              data:(NSData *)data
              type:(CBCharacteristicWriteType)type {
    if (type == CBCharacteristicWriteWithoutResponse)
        p.bwCanSend = NO;
    [self operation:p
             method:@"write"
             params:@{
                 @"attributeId" : c.remoteID,
                 @"value" : BWBytes(data),
                 @"writeType" : type == CBCharacteristicWriteWithResponse ? @2 : @1
             }
               done:^(NSDictionary *r, NSError *e) {
                 if (type == CBCharacteristicWriteWithResponse)
                     [self emit:p
                         selector:@selector(peripheral:didWriteValueForCharacteristic:error:)
                            block:^(id<CBPeripheralDelegate> d) {
                              [d peripheral:p didWriteValueForCharacteristic:c error:e];
                            }];
                 else {
                     p.bwCanSend = YES;
                     if (e)
                         NSLog(@"SimulatorBLE write without response failed: %@", e);
                     [self emit:p
                         selector:@selector(peripheralIsReadyToSendWriteWithoutResponse:)
                            block:^(id<CBPeripheralDelegate> d) {
                              [d peripheralIsReadyToSendWriteWithoutResponse:p];
                            }];
                 }
               }];
}
- (void)notify:(BWPeripheral *)p characteristic:(BWCharacteristic *)c enabled:(BOOL)enabled {
    if (!enabled)
        c.bwNotifying = NO;
    [self perform:p
        work:^(BWResult finish) {
          BWDescriptor *cccd = nil;
          for (BWDescriptor *d in c.allDescriptors)
              if ([d.UUID isEqual:[CBUUID UUIDWithString:@"2902"]])
                  cccd = d;
          if (!cccd) {
              finish(nil, BWError(@"CCCD not found"));
              return;
          }
          [self.rpc request:@"notification.set"
              params:@{
                  @"connectionId" : p.connectionID,
                  @"attributeId" : c.remoteID,
                  @"enabled" : @(enabled)
              }
              completion:^(NSDictionary *r, NSError *e) {
                if (BWStatus(r, e)) {
                    finish(r, e);
                    return;
                }
                [self.rpc request:@"descriptor.write"
                           params:@{
                               @"connectionId" : p.connectionID,
                               @"attributeId" : cccd.remoteID,
                               @"value" : enabled ? @[ @1, @0 ] : @[ @0, @0 ]
                           }
                       completion:finish];
              }];
        }
        done:^(NSDictionary *r, NSError *e) {
          c.bwNotifying = enabled && !e;
          [self emit:p
              selector:@selector(peripheral:didUpdateNotificationStateForCharacteristic:error:)
                 block:^(id<CBPeripheralDelegate> d) {
                   [d peripheral:p didUpdateNotificationStateForCharacteristic:c error:e];
                 }];
        }];
}
- (void)readRSSI:(BWPeripheral *)p {
    [self operation:p
             method:@"rssi"
             params:@{}
               done:^(NSDictionary *r, NSError *e) {
                 [self emit:p
                     selector:@selector(peripheral:didReadRSSI:error:)
                        block:^(id<CBPeripheralDelegate> d) {
                          [d peripheral:p didReadRSSI:r[@"rssi"] ?: @0 error:e];
                        }];
               }];
}
- (void)readDescriptor:(BWPeripheral *)p descriptor:(BWDescriptor *)d {
    [self operation:p
             method:@"descriptor.read"
             params:@{@"attributeId" : d.remoteID}
               done:^(NSDictionary *r, NSError *e) {
                 if (!e)
                     d.bwValue = BWData(r[@"value"]);
                 [self emit:p
                     selector:@selector(peripheral:didUpdateValueForDescriptor:error:)
                        block:^(id<CBPeripheralDelegate> delegate) {
                          [delegate peripheral:p didUpdateValueForDescriptor:d error:e];
                        }];
               }];
}
- (void)writeDescriptor:(BWPeripheral *)p descriptor:(BWDescriptor *)d data:(NSData *)data {
    [self operation:p
             method:@"descriptor.write"
             params:@{@"attributeId" : d.remoteID, @"value" : BWBytes(data)}
               done:^(NSDictionary *r, NSError *e) {
                 if (!e)
                     d.bwValue = data;
                 [self emit:p
                     selector:@selector(peripheral:didWriteValueForDescriptor:error:)
                        block:^(id<CBPeripheralDelegate> delegate) {
                          [delegate peripheral:p didWriteValueForDescriptor:d error:e];
                        }];
               }];
}
- (void)dealloc {
    for (BWPeripheral *p in _known.allValues)
        [p.operations removeAllObjects];
    [_rpc stop];
}
@end
#endif
