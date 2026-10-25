import Foundation
import CoreGraphics

/// Bounded caches retain immutable geometry. UI-only state never belongs in their keys.
final class RenderCache<Key: Hashable, Value>: @unchecked Sendable {
    private final class Entry {
        let key:Key
        var value:Value
        var cost:Int
        weak var previous:Entry?
        var next:Entry?
        init(_ key:Key,_ value:Value,_ cost:Int) { self.key = key;self.value = value;self.cost = cost }
    }
    private let lock = NSLock()
    private var entries:[Key:Entry] = [:]
    private var newest:Entry?
    private var oldest:Entry?
    private let capacity:Int
    private let costLimit:Int
    private let costOf:(Key,Value)->Int
    private var totalCost = 0
    var retainedCost:Int { lock.lock();defer { lock.unlock() };return totalCost }
    init(capacity:Int = 128,costLimit:Int = .max,cost:@escaping (Key,Value)->Int = { _,_ in 1 }) { self.capacity = max(1,capacity);self.costLimit = max(1,costLimit);self.costOf = cost }
    private func touch(_ entry:Entry) {
        guard newest !== entry else { return }
        entry.previous?.next = entry.next
        entry.next?.previous = entry.previous
        if oldest === entry { oldest = entry.previous }
        entry.previous = nil;entry.next = newest;newest?.previous = entry
        newest = entry
        if oldest == nil { oldest = entry }
    }
    private func remove(_ entry:Entry) {
        entry.previous?.next = entry.next
        entry.next?.previous = entry.previous
        if newest === entry { newest = entry.next }
        if oldest === entry { oldest = entry.previous }
        entries.removeValue(forKey:entry.key)
        totalCost -= entry.cost
        entry.next = nil; entry.previous = nil
    }
    private func store(_ value:Value,for key:Key) {
        let cost = max(1,costOf(key,value))
        if let entry = entries[key] { remove(entry) }
        guard cost <= costLimit else { return }
        while entries.count >= capacity || totalCost > costLimit-cost {
            guard let victim = oldest else { break }
            remove(victim)
        }
        let entry = Entry(key,value,cost);entries[key] = entry;totalCost += cost;touch(entry)
    }
    func cachedValue(for key:Key) -> Value? {
        lock.lock();defer { lock.unlock() }
        guard let entry = entries[key] else { return nil }
        touch(entry);return entry.value
    }
    func removeAll() { lock.lock();defer { lock.unlock() };entries.removeAll();oldest=nil;newest=nil;totalCost=0 }
    func insert(_ value:Value,for key:Key) {
        lock.lock();defer { lock.unlock() };store(value,for:key)
    }
    func value(for key:Key,make:() throws -> Value) rethrows -> Value {
        if let hit = cachedValue(for:key) { return hit }
        let value = try make()
        lock.lock();defer { lock.unlock() }
        // A worker may have completed the same key while this one rendered.
        if let entry = entries[key] { touch(entry);return entry.value }
        store(value,for:key);return value
    }

}
